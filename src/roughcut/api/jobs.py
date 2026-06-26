from __future__ import annotations

import asyncio
import base64
import bisect
import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Callable, Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, distinct, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from pydantic import BaseModel, Field

from roughcut.api.options import normalize_job_language, normalize_workflow_template
from roughcut.api.schemas import (
    ContentProfileApprovalStatsOut,
    ContentProfileMemoryStatsOut,
    ContentProfileConfirmIn,
    ContentProfileReviewOut,
    JobAgentDecisionOut,
    JobAgentPlanApplyIn,
    JobAgentPlanOut,
    JobAgentPlanRefineIn,
    JobActivityOut,
    JobInitializeIn,
    JobOut,
    JobsUsageSummaryOut,
    JobsUsageTrendOut,
    OpenFolderOut,
    ReportOut,
    ReviewApplyRequest,
    StrategyReviewGateConfirmIn,
    TokenUsageReportOut,
    normalize_execution_mode,
    normalize_job_flow_mode,
    resolve_job_flow_mode_from_execution_mode,
)
from roughcut.avatar import get_avatar_material_profile, list_avatar_material_profiles
from roughcut.config import DEFAULT_PROJECT_ROOT, get_settings, llm_task_route
from roughcut.config import apply_runtime_overrides
from roughcut.creator_asset_runtime import creator_has_complete_packaging_assets
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.db.models import (
    Artifact,
    CreatorCard,
    CreatorPublicationProfile,
    CreatorTaskStrategy,
    CreatorVisualPlan,
    ContentProfileCorrection,
    ContentProfileKeywordStat,
    FactClaim,
    FactEvidence,
    GlossaryTerm,
    Job,
    JobAgentPlan,
    JobStep,
    RenderOutput,
    ReviewAction,
    SubtitleCorrection,
    SubtitleItem,
    Timeline,
    TranscriptSegment,
)
from roughcut.db.session import get_session, get_session_factory
from roughcut.edit.cut_analysis import (
    ARTIFACT_TYPE_CUT_ANALYSIS,
    CUT_ANALYSIS_SCHEMA_VERSION,
    build_cut_analysis_payload,
    cut_analysis_accepted_cuts,
    cut_analysis_effective_applied_cuts,
    cut_analysis_candidate_items,
    cut_analysis_rule_candidates,
    cut_analysis_silence_segments,
)
from roughcut.edit.capabilities import CAPABILITY_KEYS
from roughcut.edit.product_controls import (
    normalize_automation_level,
    normalize_edit_mode,
    normalize_material_usage,
    workflow_template_for_edit_mode,
)
from roughcut.edit.editorial_timeline import (
    build_editorial_segments_from_keep_segments as build_shared_editorial_segments_from_keep_segments,
    editorial_cut_segments,
    editorial_timeline_analysis,
    editorial_timeline_subtitle_projection,
    normalize_keep_segments_payloads,
    resolve_editorial_keep_segments,
)
from roughcut.edit.local_focus_plan import build_local_focus_plan
from roughcut.edit.packaging_timeline import (
    packaging_timeline_analysis,
    packaging_timeline_asset_plan,
    packaging_timeline_chapter_analysis,
    packaging_timeline_editing_accents,
    packaging_timeline_editing_skill,
    packaging_timeline_hyperframes_options,
    packaging_timeline_insert_plan,
    packaging_timeline_subtitles,
    resolve_packaging_timeline_payload,
)
from roughcut.edit.rule_registry import (
    build_rule_catalog,
    manual_editor_synthetic_timeline_reasons,
    manual_editor_frontend_managed_auto_cut_reasons,
    rule_kind,
    rule_label,
    rule_match_surface_layer,
)
from roughcut.host.file_manager import can_open_in_file_manager, describe_file_manager_target, open_in_file_manager
from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token
from roughcut.intelligent_copy_layout import (
    resolve_smart_copy_material_json_path,
    resolve_smart_copy_platform_packaging_json_path,
)
from roughcut.production_readiness import (
    insert_plan_output_fallback_reasons,
    projection_output_fallback_reasons,
)
from roughcut.edit.refine_decisions import (
    ARTIFACT_TYPE_REFINE_DECISION_PLAN,
    REFINE_DECISION_PLAN_SCHEMA_VERSION,
    build_refine_decision_plan_from_render_plan,
    build_refine_decision_plan_payload,
    normalize_refine_decision_plan_strategy_metadata,
)
from roughcut.edit.render_plan import (
    render_plan_avatar_commentary,
    render_plan_delivery,
    render_plan_dialogue_polish,
    render_plan_loudness,
    render_plan_strategy_review_context,
    render_plan_voice_processing,
    render_plan_video_transform,
    render_plan_workflow_preset,
)
from roughcut.edit.multimodal_trim_review import (
    ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,
    apply_multimodal_trim_review_to_cut_analysis,
    build_multimodal_trim_review_payload,
    multimodal_trim_review_matches_cut_analysis,
    review_multimodal_trim_review_payload,
)
from roughcut.edit.manual_editor_contract import (
    manual_editor_apply_detail as _shared_manual_editor_apply_detail,
    manual_editor_change_contract as _shared_manual_editor_change_contract,
    manual_editor_rerun_plan as _shared_manual_editor_rerun_plan,
    manual_editor_rerun_issue_code as _shared_manual_editor_rerun_issue_code,
)
from roughcut.edit.smart_cut_rules import (
    SMART_DELETE_AUTO_EDIT_REASONS,
    default_smart_cut_rules_payload,
    normalize_smart_cut_rules_payload,
)
from roughcut.edit.strategy_profile import normalize_strategy_type
from roughcut.edit.strategy_review_gates import (
    build_strategy_review_gate_confirmations_payload,
    normalize_strategy_review_gate_confirmations,
)
from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_rule_text,
    subtitle_semantic_item_text,
    subtitle_surface_item_dict,
)
from roughcut.pipeline.celery_app import celery_app
from roughcut.pipeline.job_rerun import (
    JobRerunPlan,
    JobRerunRequest,
    build_job_rerun_detail,
    execute_job_rerun_plan,
    resolve_job_rerun_request,
)
from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.media.manual_editor_assets import (
    ensure_manual_editor_preview_assets,
    load_manual_editor_preview_assets,
    mark_manual_editor_preview_assets_queued,
    manual_editor_asset_dir,
)
from roughcut.media.output import get_output_project_dir
from roughcut.media.subtitles import remap_subtitles_to_timeline, split_subtitle_display_item
from roughcut.media.subtitle_text import (
    clean_subtitle_payloads,
    preserve_subtitle_payloads,
    normalize_contextual_noc_alias_text,
    normalize_contextual_unboxing_sale_text,
    normalize_editable_subtitle_text,
    normalize_flashlight_model_alias_text,
    normalize_source_transcript_text,
)
from roughcut.media.subtitle_projection_validation import (
    annotate_projected_subtitle_sources,
    projection_has_source_text_mismatch,
    source_ranges_for_output_range,
    validate_projected_subtitles_against_source,
    validate_projected_subtitles_against_transcript,
)
from roughcut.media.variant_timeline_bundle import (
    variant_cut_evidence_summary,
    variant_high_energy_keeps,
    variant_high_risk_cuts,
    variant_llm_cut_review,
    variant_multimodal_trim_review_summary,
    variant_refine_decision_summary,
    variant_review_flags,
    variant_timeline_diagnostics,
)
from roughcut.media.subtitle_spans import (
    drop_redundant_synthetic_word_payloads,
    has_unsafe_unmatched_alnum_units,
    sanitize_transcript_segment_word_rows,
    subtitle_display_unit_key,
    subtitle_display_units,
    subtitle_span_alignment_diagnostics,
    subtitle_span_token_payloads,
    word_payloads_have_collapsed_timing,
)
from roughcut.publication_intelligence import generate_publication_scheme
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.media.subtitle_fingerprint import subtitle_payload_fingerprint
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER
from roughcut.speech.subtitle_pipeline import SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION
from roughcut.speech.subtitle_pipeline import canonical_transcript_data_is_current
from roughcut.speech.subtitle_pipeline import subtitle_projection_data_is_current
from roughcut.speech.subtitle_segmentation import SubtitleEntry, analyze_subtitle_segmentation, segment_subtitles
from roughcut.publication import (
    active_publication_credentials,
    build_publication_plan,
    check_publication_browser_agent_ready,
    list_publication_attempts,
    normalize_publication_platform,
    publication_adapter_requires_browser_agent,
    publication_plan_is_publishable,
    publication_plan_is_manual_handoff_ready,
    publication_plan_status,
    submit_publication_attempts,
)
from roughcut.publication_packaging import load_publication_packaging_payload, normalize_publication_packaging_payload
from roughcut.pipeline.quality import QUALITY_ARTIFACT_TYPE
from roughcut.media.variant_timeline_bundle import resolve_effective_variant_timeline_bundle
from roughcut.packaging.library import resolve_packaging_plan_for_job
from roughcut.recovery.stuck_step_recovery import STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE
from roughcut.review.content_understanding_schema import normalize_video_type
from roughcut.review.content_profile import _probe_duration, build_reviewed_transcript_excerpt
from roughcut.review.intelligent_copy import generate_intelligent_copy, rerender_existing_intelligent_copy_cover_groups
from roughcut.review.content_profile_feedback import apply_content_profile_feedback
from roughcut.review.content_profile_keywords import normalize_query_list
from roughcut.review.content_profile_memory import (
    _build_field_preferences,
    _build_keyword_preferences,
    _build_recent_corrections,
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)
from roughcut.review.content_profile_artifacts import (
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS,
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
    ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
    ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
    build_strategy_storyboard_review_artifact_payload,
    build_strategy_timeline_preview_artifact_payload,
    build_strategy_review_gates_artifact_payload,
)
from roughcut.review.chapter_analysis import (
    ARTIFACT_TYPE_CHAPTER_ANALYSIS,
    build_chapter_analysis_payload,
)
from roughcut.review.content_profile_strategy import (
    attach_content_profile_capability_orchestration,
    build_content_profile_local_asset_inventory,
    extract_content_profile_source_context_from_steps,
    resolve_job_merged_source_names,
)
from roughcut.review.hotword_learning import load_learned_hotwords, upsert_learned_hotword
from roughcut.review.downstream_context import (
    attach_strategy_review_context,
    build_downstream_context,
    resolve_downstream_profile,
    select_strategy_review_artifact_context,
    strip_publication_only_profile_fields,
)
from roughcut.review.final_review_rerun import (
    build_final_review_rerun_plans,
    combine_final_review_rerun_plans,
    extract_final_review_content_profile_feedback,
)
from roughcut.review.final_review_state import (
    apply_final_review_rerun_metadata,
    mark_final_review_approved,
    mark_final_review_pending,
)
from roughcut.review.model_identity import model_numbers_conflict
from roughcut.review.content_profile_review_stats import (
    apply_current_content_profile_review_policy,
    build_content_profile_auto_review_gate,
    summarize_content_profile_review_stats,
    record_content_profile_manual_review,
)
from roughcut.review.domain_glossaries import detect_glossary_domains, resolve_builtin_glossary_terms
from roughcut.review.subtitle_memory import build_subtitle_review_memory
from roughcut.review.subtitle_consistency import ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
from roughcut.review.subtitle_quality import (
    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
    subtitle_items_have_output_fallback_alignment,
)
from roughcut.review.subtitle_review_actions import (
    build_subtitle_candidate_action,
    build_subtitle_consistency_action,
    build_subtitle_quality_action,
    build_subtitle_review_context,
    build_subtitle_term_resolution_action,
    select_latest_subtitle_artifact_payloads,
)
from roughcut.review.subtitle_term_resolution import ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH
from roughcut.review.report import generate_report
from roughcut.runtime_refresh_hold import touch_runtime_refresh_hold
from roughcut.storage.s3 import get_storage, job_key
from roughcut.storage.runtime_cleanup import cleanup_job_runtime_files
from roughcut.source_context import enrich_source_context_with_filename_hints
from roughcut.usage import build_job_token_report, build_jobs_usage_summary, build_jobs_usage_trend
from roughcut.edit.decisions import infer_timeline_analysis
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.render_plan import build_render_plan, build_smart_editing_accents, save_render_plan
from roughcut.hyperframes import normalize_options as normalize_hyperframes_options

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)
_MANUAL_EDITOR_ASSET_WARMUPS: set[str] = set()
_MANUAL_EDITOR_ASSET_WARMUPS_LOCK = threading.Lock()
_MANUAL_EDITOR_ASSET_WARMUP_SEMAPHORE = threading.Semaphore(1)

_CONTENT_PROFILE_PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAJABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwCiiitzI//9k="
)

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
    "dialogue_polish": "智能台词润色",
    "avatar_commentary": "数字人解说",
    "edit_plan": "剪辑决策",
    "chapter_analysis": "进度条章节",
    "render": "渲染输出",
    "script_footage_remix": "解说二创",
}

STEP_ORDER = {step_name: index for index, step_name in enumerate(PIPELINE_STEPS)}
MANUAL_EDITOR_OPTIONAL_PREREQUISITE_STEPS = {"dialogue_polish", "avatar_commentary"}
_LIST_PREVIEW_ARTIFACT_TYPES = (
    "content_profile_final",
    "content_profile",
    "content_profile_draft",
    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
    ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
    ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
    QUALITY_ARTIFACT_TYPE,
    "variant_timeline_bundle",
    "render_outputs",
    "platform_packaging_md",
    "avatar_commentary_plan",
)

PROFILE_ARTIFACT_PRIORITY = {
    "content_profile_final": 3,
    "content_profile": 1,
    "content_profile_draft": 1,
}
_CONTENT_PROFILE_ARTIFACT_TYPES = ("content_profile_final", "content_profile", "content_profile_draft")
_MATERIAL_ENHANCEMENT_MODES = frozenset({"auto_orientation_correction", "voice_enhancement", "loudness_normalization"})
_DOWNSTREAM_PROFILE_ARTIFACT_TYPES = (
    "downstream_context",
    *_CONTENT_PROFILE_ARTIFACT_TYPES,
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
    ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
    ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
)
_CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION = "v7"
_CONTENT_PROFILE_THUMBNAIL_LOCKS: dict[str, asyncio.Lock] = {}
_CONTENT_PROFILE_THUMBNAIL_GENERATION_SEMAPHORE = asyncio.Semaphore(2)
_CONTENT_PROFILE_THUMBNAIL_WARM_TASKS: dict[str, asyncio.Task] = {}
_CONTENT_PROFILE_PLACEHOLDER_RETRY_SECONDS = 300
_FILE_RESPONSE_CACHE_TTL_SEC = 300.0
_FILE_RESPONSE_CACHE_MAX = 512
_FILE_RESPONSE_CACHE_LOCK = threading.Lock()
_FILE_RESPONSE_CACHE: dict[str, tuple[float, str, int, int]] = {}


class FinalReviewDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class FinalReviewDecisionOut(BaseModel):
    job_id: str
    decision: Literal["approve", "reject"]
    job_status: str
    review_step_status: str
    rerun_triggered: bool = False
    note: str | None = None


class FinalReviewVariantTimelineRerenderOut(BaseModel):
    job_id: str
    job_status: str
    rerun_steps: list[str]
    validation_status: str | None = None
    validation_issue_count: int = 0


class JobRerunActionIn(BaseModel):
    issue_code: str | None = None
    rerun_start_step: str | None = None
    note: str | None = None


class JobRerunActionOut(BaseModel):
    job_id: str
    job_status: str
    rerun_start_step: str
    rerun_steps: list[str]
    issue_codes: list[str]
    note: str | None = None
    detail: str | None = None


class JobDownloadFileOut(BaseModel):
    id: str
    label: str
    filename: str
    kind: str
    size_bytes: int
    recommended: bool = True


class JobDownloadFilesOut(BaseModel):
    job_id: str
    files: list[JobDownloadFileOut]


class JobDownloadZipIn(BaseModel):
    file_ids: list[str] = Field(default_factory=list)


class ManualEditorSegmentIn(BaseModel):
    start: float
    end: float


class ManualEditorSubtitleOverrideIn(BaseModel):
    index: int
    start_time: float | None = None
    end_time: float | None = None
    text_final: str | None = None
    delete: bool = False


class ManualEditorSubtitleReplacementIn(BaseModel):
    original: str
    replacement: str
    occurrence_count: int = 1


class ManualEditorVideoTransformIn(BaseModel):
    rotation_cw: int = 0
    aspect_ratio: str | None = None
    resolution_mode: str | None = None
    resolution_preset: str | None = None


class ManualEditorApplyIn(BaseModel):
    keep_segments: list[ManualEditorSegmentIn] = Field(default_factory=list)
    subtitle_overrides: list[ManualEditorSubtitleOverrideIn] = Field(default_factory=list)
    subtitle_replacements: list[ManualEditorSubtitleReplacementIn] = Field(default_factory=list)
    video_transform: ManualEditorVideoTransformIn | None = None
    smart_cut_rules: dict[str, Any] | None = None
    hyperframes_options: dict[str, Any] | None = None
    video_summary: str | None = None
    base_timeline_id: str | None = None
    base_timeline_version: int | None = None
    base_render_plan_version: int | None = None
    base_subtitle_fingerprint: str | None = None
    note: str | None = None


MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE = "manual_editor_draft"
MANUAL_EDITOR_DRAFT_SCHEMA = "manual_editor_draft.v2"
MANUAL_EDITOR_TIMELINE_RULES_VERSION = 3
MANUAL_EDITOR_MICRO_CUT_HEAL_SEC = 0.18


class PublicationSubmitIn(BaseModel):
    creator_profile_id: str | None = None
    platforms: list[str] = Field(default_factory=list)
    platform_options: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ManualEditorSegmentOut(BaseModel):
    start: float
    end: float
    duration_sec: float
    source_index: int


class ManualEditorSilenceOut(BaseModel):
    start: float
    end: float
    duration_sec: float
    source: str = "audio_vad"

class ManualEditorRuleSegmentOut(BaseModel):
    start: float
    end: float
    duration_sec: float
    kind: Literal["filler", "catchphrase", "repeated", "pause", "smart_delete"]
    reason: str
    source: str = "auto_edit_decision"
    stage: str = "accepted_cut"
    rule_id: str | None = None
    match_surface: str | None = None
    match_surface_layer: str | None = None
    risk_level: str | None = None
    confidence: float | None = None
    detail: str | None = None
    evidence: list[str] = Field(default_factory=list)
    auto_applied: bool = True
    filler_mode: Literal["standalone", "sentence_head", "sentence_tail", "continuous"] | None = None
    source_text: str | None = None


class ManualEditorWordOut(BaseModel):
    word: str
    start: float
    end: float
    confidence: float | None = None
    source: str | None = None


class ManualEditorSubtitleSpanTokenOut(BaseModel):
    text: str
    start: float
    end: float
    source: str | None = None


class ManualEditorSubtitleOut(BaseModel):
    index: int
    source_index: int | None = None
    source_indexes: list[int] = Field(default_factory=list)
    projection_source: str | None = None
    source_fragment_index: int | None = None
    source_fragment_count: int | None = None
    source_overlap_start_time: float | None = None
    source_overlap_end_time: float | None = None
    source_text_full: str | None = None
    start_time: float
    end_time: float
    text_raw: str | None = None
    text_norm: str | None = None
    text_final: str | None = None
    transcript_text: str | None = None
    timing_text: str | None = None
    display_suppressed_reason: str | None = None
    words: list[ManualEditorWordOut] = Field(default_factory=list)
    alignment_tokens: list[ManualEditorSubtitleSpanTokenOut] = Field(default_factory=list)
    alignment_diagnostics: dict[str, Any] | None = None


class ManualEditorSessionOut(BaseModel):
    job_id: str
    timeline_id: str
    timeline_version: int
    render_plan_version: int | None = None
    subtitle_fingerprint: str | None = None
    source_name: str
    source_duration_sec: float
    source_url: str | None = None
    video_summary: str | None = None
    base_video_summary: str | None = None
    keep_segments: list[ManualEditorSegmentOut] = Field(default_factory=list)
    base_keep_segments: list[ManualEditorSegmentOut] = Field(default_factory=list)
    silence_segments: list[ManualEditorSilenceOut] = Field(default_factory=list)
    rule_segments: list[ManualEditorRuleSegmentOut] = Field(default_factory=list)
    cut_analysis: dict[str, Any] | None = None
    refine_decision_plan: dict[str, Any] | None = None
    multimodal_trim_review: dict[str, Any] | None = None
    strategy_review_context: dict[str, Any] | None = None
    source_subtitle_basis: str | None = None
    projected_subtitle_basis: str | None = None
    projection_contract_locked: bool = False
    projection_diagnostics: dict[str, Any] | None = None
    source_subtitles: list[ManualEditorSubtitleOut] = Field(default_factory=list)
    projected_subtitles: list[ManualEditorSubtitleOut] = Field(default_factory=list)
    subtitle_overrides: list[ManualEditorSubtitleOverrideIn] = Field(default_factory=list)
    video_transform: ManualEditorVideoTransformIn | None = None
    base_video_transform: ManualEditorVideoTransformIn | None = None
    smart_cut_rules: dict[str, Any] | None = None
    hyperframes_options: dict[str, bool] = Field(default_factory=dict)
    draft_saved_at: str | None = None
    draft_note: str | None = None
    editable: bool = True
    detail: str | None = None


class ManualEditorDraftOut(BaseModel):
    job_id: str
    saved_at: str
    keep_segment_count: int
    subtitle_override_count: int
    detail: str | None = None


class ManualEditorRotationDetectOut(BaseModel):
    job_id: str
    rotation_cw: int
    detail: str | None = None


class ManualEditorApplyOut(BaseModel):
    job_id: str
    timeline_id: str
    timeline_version: int
    render_plan_id: str
    render_plan_version: int
    keep_segment_count: int
    projected_subtitle_count: int
    job_status: str
    change_scope: str = "timeline"
    render_strategy: str = "full_timeline_render"
    rerun_steps: list[str] = Field(default_factory=list)
    detail: str | None = None


class ManualEditorThumbnailOut(BaseModel):
    url: str
    time_sec: float


class ManualEditorPreviewVideoSourceOut(BaseModel):
    url: str
    type: str | None = None


class ManualEditorPreviewAssetsOut(BaseModel):
    job_id: str
    ready: bool = True
    video_ready: bool = False
    audio_ready: bool = False
    warming: bool = False
    asset_version: int = 0
    status: str | None = None
    stage: str | None = None
    progress: float | None = None
    video_url: str | None = None
    video_sources: list[ManualEditorPreviewVideoSourceOut] = Field(default_factory=list)
    audio_url: str | None = None
    duration_sec: float = 0.0
    sample_rate: int = 16000
    peaks: list[float] = Field(default_factory=list)
    peak_count: int = 0
    silence_intervals: list[ManualEditorSilenceOut] = Field(default_factory=list)
    audio_peak: float = 0.0
    audio_rms: float = 0.0
    audio_lufs: float = 0.0
    audio_true_peak_db: float = 0.0
    target_lufs: float = -16.0
    auto_volume_gain: float = 1.0
    thumbnail_urls: list[str] = Field(default_factory=list)
    thumbnail_items: list[ManualEditorThumbnailOut] = Field(default_factory=list)
    orientation_decision: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    detail: str | None = None
    error: str | None = None
    updated_at: str | None = None


class ManualEditorReadinessStepOut(BaseModel):
    step_name: str
    label: str
    status: str
    progress: float | None = None
    detail: str | None = None


class ManualEditorReadinessOut(BaseModel):
    job_id: str
    status: Literal["preprocessing", "ready", "failed", "blocked"]
    can_open_editor: bool = False
    can_edit: bool = False
    progress_percent: int = 0
    current_step: str | None = None
    detail: str | None = None
    required_steps: list[ManualEditorReadinessStepOut] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


_MANUAL_EDITOR_SPLIT_STRATEGY_NO_SPLIT = "no_split"
_MANUAL_EDITOR_SPLIT_STRATEGY_WORD_TIMED = "subtitle_segmentation_word_timed"
_MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_NO_WORDS = "display_fallback_no_words"
_MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_NO_SEGMENTATION_OUTPUT = "display_fallback_no_segmentation_output"
_MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_SEGMENTATION_MISMATCH = "display_fallback_segmentation_mismatch"


def _ensure_content_understanding_payload(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return profile
    enriched = dict(profile)
    existing_block = profile.get("content_understanding") if isinstance(profile.get("content_understanding"), dict) else {}
    content_understanding = dict(existing_block)

    def _first_text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _list_value(value: Any) -> list[Any]:
        return list(value) if isinstance(value, list) else []

    normalized_search_queries = normalize_query_list(
        [str(item).strip() for item in _list_value(content_understanding.get("search_queries")) if str(item).strip()]
    )
    if not normalized_search_queries:
        normalized_search_queries = normalize_query_list(
            [str(item).strip() for item in _list_value(enriched.get("search_queries")) if str(item).strip()]
        )

    if "needs_review" in content_understanding:
        needs_review = bool(content_understanding.get("needs_review"))
    else:
        needs_review = bool(enriched.get("review_required") or False)

    review_reasons = _list_value(content_understanding.get("review_reasons"))
    if not review_reasons:
        review_reasons = [str(item).strip() for item in _list_value(enriched.get("review_reasons")) if str(item).strip()]
    else:
        review_reasons = [str(item).strip() for item in review_reasons if str(item).strip()]

    content_understanding.update(
        {
            "video_type": normalize_video_type(
                _first_text(
                    content_understanding.get("video_type"),
                    enriched.get("content_kind"),
                    enriched.get("video_type"),
                    enriched.get("subject_type"),
                    content_understanding.get("subject_type"),
                )
            ),
            "content_domain": _first_text(
                content_understanding.get("content_domain"),
                enriched.get("subject_domain"),
                enriched.get("content_domain"),
            ),
            "primary_subject": _first_text(
                content_understanding.get("primary_subject"),
                enriched.get("primary_subject"),
                enriched.get("subject_type"),
            ),
            "subject_entities": _list_value(content_understanding.get("subject_entities")),
            "video_theme": _first_text(content_understanding.get("video_theme"), enriched.get("video_theme")),
            "summary": _first_text(content_understanding.get("summary"), enriched.get("summary")),
            "hook_line": _first_text(content_understanding.get("hook_line"), enriched.get("hook_line")),
            "engagement_question": _first_text(
                content_understanding.get("engagement_question"),
                content_understanding.get("question"),
                enriched.get("engagement_question"),
                enriched.get("question"),
            ),
            "search_queries": normalized_search_queries,
            "evidence_spans": _list_value(content_understanding.get("evidence_spans")),
            "timed_focus_spans": _list_value(content_understanding.get("timed_focus_spans")),
            "uncertainties": _list_value(content_understanding.get("uncertainties")),
            "confidence": dict(content_understanding.get("confidence")) if isinstance(content_understanding.get("confidence"), dict) else {},
            "needs_review": needs_review,
            "review_reasons": review_reasons,
        }
    )
    enriched["content_understanding"] = content_understanding
    return enriched


def _build_content_profile_local_asset_inventory(job: Job | None, profile: dict[str, Any] | None) -> dict[str, Any]:
    return build_content_profile_local_asset_inventory(job, profile)


def _infer_content_profile_strategy_type(
    profile: dict[str, Any] | None,
    *,
    local_asset_inventory: dict[str, Any] | None = None,
) -> str:
    enriched = attach_content_profile_capability_orchestration(profile, job=None)
    if isinstance(enriched, dict):
        orchestration = enriched.get("capability_orchestration")
        if isinstance(orchestration, dict):
            return str(orchestration.get("strategy_type") or "").strip() or "information_density"
    return "information_density"


def _normalize_json_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be a JSON list of strings") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON list of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_selected_smart_cut_rule_reasons(value: Any) -> list[str]:
    requested = _normalize_json_string_list(value, field_name="smart_cut_rule_reasons")
    valid_reasons = {
        str(item.get("reason") or "").strip()
        for item in build_rule_catalog()
        if str(item.get("reason") or "").strip()
    }
    return [reason for reason in requested if reason in valid_reasons]


def _smart_cut_rules_payload_from_selected_reasons(reasons: list[str]) -> dict[str, Any]:
    selected = set(reasons)
    selected_smart_delete_reasons = [
        reason for reason in SMART_DELETE_AUTO_EDIT_REASONS if reason in selected
    ]
    defaults = default_smart_cut_rules_payload()
    return {
        **defaults,
        "enabled_reasons": list(reasons),
        "fillerEnabled": bool(selected.intersection({"filler_word"})),
        "catchphraseEnabled": bool(selected.intersection({"catchphrase_phrase"})),
        "repeatedEnabled": bool(selected.intersection({"repeated_speech"})),
        "pauseEnabled": bool(selected.intersection({"silence", "pause"})),
        "smartDeleteEnabled": bool(selected_smart_delete_reasons),
        "disabledSmartDeleteReasons": [
            reason for reason in SMART_DELETE_AUTO_EDIT_REASONS if reason not in selected_smart_delete_reasons
        ],
    }


def _normalize_material_enhancement_modes(value: Any) -> list[str]:
    requested = _normalize_json_string_list(value, field_name="material_enhancement_modes")
    return [mode for mode in requested if mode in _MATERIAL_ENHANCEMENT_MODES]


def _normalize_translation_target_language(value: Any) -> str:
    normalized = str(value or "auto").strip()
    return normalized if normalized in {"auto", "en-US", "zh-CN", "ja-JP", "ko-KR"} else "auto"


def _normalize_create_start_mode(value: Any) -> str:
    normalized = str(value or "immediate").strip().lower()
    return normalized if normalized in {"manual", "immediate"} else "immediate"


def _normalize_agent_capability_keys(value: Any) -> list[str]:
    requested = _normalize_json_string_list(value, field_name="agent_capability_keys")
    valid = set(CAPABILITY_KEYS)
    return [key for key in requested if key in valid]


def _normalize_hyperframes_options_payload(value: Any) -> dict[str, bool]:
    if value is None:
        return normalize_hyperframes_options(None)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return normalize_hyperframes_options(None)
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("hyperframes_options must be a JSON object") from exc
    else:
        payload = value
    if not isinstance(payload, dict):
        raise ValueError("hyperframes_options must be a JSON object")
    return normalize_hyperframes_options(payload)


def _merge_hyperframes_enhancement_modes(
    enhancement_modes: list[str],
    hyperframes_options: dict[str, bool],
) -> list[str]:
    modes = list(enhancement_modes or [])
    if hyperframes_options.get("smart_effects") and "ai_effects" not in modes:
        modes.append("ai_effects")
    return normalize_enhancement_modes(modes)


def _capability_overrides_from_selected_keys(keys: list[str]) -> dict[str, str]:
    selected = set(keys)
    return {key: "disabled" for key in CAPABILITY_KEYS if key not in selected}


def _smart_cut_rule_reasons_from_capabilities(
    smart_cut_reasons: list[str] | None,
    capability_keys: list[str] | None,
) -> list[str] | None:
    if smart_cut_reasons is not None:
        return list(smart_cut_reasons)
    if capability_keys is None:
        return smart_cut_reasons
    selected_capabilities = set(capability_keys)
    if "speech_density_trim" not in selected_capabilities:
        return []
    enabled: list[str] = []
    for reason in ("filler_word", "repeated_speech", "silence", "low_signal_subtitle"):
        if reason not in enabled:
            enabled.append(reason)
    return enabled


def _merge_smart_cut_capability_key(
    keys: list[str] | None,
    smart_cut_reasons: list[str] | None,
) -> list[str] | None:
    if keys is None:
        return None
    selected = [key for key in keys if key != "speech_density_trim"]
    return [*selected, "speech_density_trim"] if smart_cut_reasons else selected


def _merge_hyperframes_capability_keys(
    keys: list[str] | None,
    hyperframes_options: dict[str, bool],
) -> list[str] | None:
    if keys is None:
        return None
    selected = list(keys)
    if hyperframes_options.get("chapter_cards") and "chapter_cards" not in selected:
        selected.append("chapter_cards")
    if hyperframes_options.get("sound_cues") and "local_audio_cues" not in selected:
        selected.append("local_audio_cues")
    return [key for key in selected if key in CAPABILITY_KEYS]


def _attach_content_profile_capability_orchestration(
    profile: dict[str, Any] | None,
    *,
    job: Job | None,
) -> dict[str, Any] | None:
    payload = _ensure_content_understanding_payload(profile)
    if not isinstance(payload, dict):
        return payload
    return attach_content_profile_capability_orchestration(payload, job=job)


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
                PROFILE_ARTIFACT_PRIORITY.get(str(artifact.artifact_type or "").strip(), 0),
                artifact.created_at or epoch,
            ),
        )
    return max(
        profile_artifacts,
        key=lambda artifact: (
            PROFILE_ARTIFACT_PRIORITY.get(str(artifact.artifact_type or "").strip(), 0),
            artifact.created_at or epoch,
        ),
    )


async def _load_latest_optional_artifact(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    artifact_types: tuple[str, ...] | list[str],
) -> Artifact | None:
    query = (
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(list(artifact_types)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    if not set(artifact_types).issuperset(_CONTENT_PROFILE_ARTIFACT_TYPES):
        query = query.limit(1)
    result = await session.execute(query)
    artifacts = result.scalars().all()
    if set(artifact_types).issuperset(_CONTENT_PROFILE_ARTIFACT_TYPES):
        return _select_preferred_content_profile_artifact(artifacts)
    return artifacts[0] if artifacts else None


async def _load_manual_editor_preferred_downstream_profile(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> tuple[Artifact | None, dict[str, Any]]:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(list(_DOWNSTREAM_PROFILE_ARTIFACT_TYPES)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts = result.scalars().all()
    artifact = _select_preferred_downstream_artifact(artifacts)
    if artifact is None:
        return None, {}
    profile = resolve_downstream_profile(artifact.data_json if isinstance(artifact.data_json, dict) else {})
    return artifact, attach_strategy_review_context(
        profile,
        select_strategy_review_artifact_context(artifacts),
    )


def _manual_editor_projection_has_suspicious_subtitle_timing(
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


def _manual_editor_subtitle_item_payload(item: SubtitleItem) -> dict[str, Any]:
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


def _manual_editor_subtitle_projection_entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
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
    for key in (
        "source_index",
        "source_indexes",
        "source_fragment_index",
        "source_fragment_count",
        "source_overlap_start_time",
        "source_overlap_end_time",
        "source_text_full",
        "timing_text",
        "transcript_text",
        "transcript_text_raw",
    ):
        if key in entry:
            payload[key] = entry.get(key)
    words = drop_redundant_synthetic_word_payloads(list(entry.get("words") or entry.get("words_json") or []))
    if words:
        payload["words"] = words
    return payload


async def _load_manual_editor_subtitle_items(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> list[SubtitleItem]:
    item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    return list(item_result.scalars().all())


async def _load_manual_editor_latest_subtitle_projection_entries(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    fallback_items: list[SubtitleItem] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from roughcut.pipeline.steps import _load_latest_current_canonical_transcript_data

    projection_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,),
    )
    projection_data = projection_artifact.data_json if projection_artifact and isinstance(projection_artifact.data_json, dict) else {}
    projection_entries = [
        _manual_editor_subtitle_projection_entry_payload(entry)
        for entry in list(projection_data.get("entries") or [])
        if isinstance(entry, dict)
    ]
    transcript_layer = str(projection_data.get("transcript_layer") or "").strip()
    if transcript_layer:
        projection_entries = [
            {
                **dict(entry),
                "projection_source": str(entry.get("projection_source") or transcript_layer),
            }
            for entry in projection_entries
        ]
    if projection_entries and _manual_editor_projection_data_is_current(projection_data):
        return projection_entries, projection_data
    if projection_entries:
        canonical_layer = await _load_latest_current_canonical_transcript_data(
            session,
            job_id=job_id,
        )
        rebuilt_projection_entries, rebuilt_projection_data = await _manual_editor_rebuild_projection_entries_from_canonical_layer(
            session,
            job_id=job_id,
            canonical_layer=canonical_layer,
            projection_data=projection_data,
            fallback_items=fallback_items,
        )
        if rebuilt_projection_entries:
            merged_projection_data = {
                **dict(projection_data or {}),
                **rebuilt_projection_data,
                "rebuilt_from_canonical_fallback": True,
                "projection_refresh_required": True,
            }
            return rebuilt_projection_entries, merged_projection_data
        return projection_entries, {
            **dict(projection_data or {}),
            "projection_refresh_required": True,
        }
    canonical_layer = await _load_latest_current_canonical_transcript_data(
        session,
        job_id=job_id,
    )
    rebuilt_projection_entries, rebuilt_projection_data = await _manual_editor_rebuild_projection_entries_from_canonical_layer(
        session,
        job_id=job_id,
        canonical_layer=canonical_layer,
        projection_data=projection_data,
        fallback_items=fallback_items,
    )
    if rebuilt_projection_entries:
        merged_projection_data = {
            **dict(projection_data or {}),
            **rebuilt_projection_data,
            "rebuilt_from_canonical_fallback": True,
        }
        return rebuilt_projection_entries, merged_projection_data
    if projection_entries:
        return projection_entries, projection_data
    return [_manual_editor_subtitle_item_payload(item) for item in list(fallback_items or [])], {}


async def _load_manual_editor_latest_subtitle_payloads(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    fallback_to_items: bool = True,
    drop_empty: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    subtitle_dicts, projection_data = await _load_manual_editor_latest_subtitle_projection_entries(
        session,
        job_id=job_id,
        fallback_items=None,
    )
    projection_refresh_required = bool(projection_data.get("projection_refresh_required"))
    if subtitle_dicts:
        cleaned_subtitles = preserve_subtitle_payloads(subtitle_dicts, drop_empty=drop_empty)
        split_profile = projection_data.get("split_profile") if isinstance(projection_data.get("split_profile"), dict) else {}
        if (
            not projection_refresh_required
            and (
                not fallback_to_items
                or not _manual_editor_projection_has_suspicious_subtitle_timing(
                    cleaned_subtitles,
                    split_profile=split_profile,
                )
            )
        ):
            return cleaned_subtitles, projection_data
    elif not fallback_to_items:
        return [], projection_data
    subtitle_items = await _load_manual_editor_subtitle_items(session, job_id=job_id) if fallback_to_items else []
    if subtitle_items:
        subtitle_item_projection_data = {
            **dict(projection_data or {}),
            "projection_kind": "subtitle_item_baseline",
            "transcript_layer": "subtitle_item",
        }
        return (
            clean_subtitle_payloads(
                [_manual_editor_subtitle_item_payload(item) for item in subtitle_items],
                drop_empty=drop_empty,
            ),
            subtitle_item_projection_data,
        )
    return clean_subtitle_payloads(
        [_manual_editor_subtitle_item_payload(item) for item in subtitle_items],
        drop_empty=drop_empty,
    ), {}


def _coerce_artifact_payload(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None or not isinstance(artifact.data_json, dict):
        return {}
    return dict(artifact.data_json)


def _normalize_manual_video_summary(value: Any) -> str | None:
    text = "\n".join(
        line.strip()
        for line in str(value or "").replace("\r", "\n").split("\n")
        if line.strip()
    )
    if not text:
        return None
    return text[:1200]


def _select_preferred_downstream_artifact(artifacts: list[Artifact]) -> Artifact | None:
    priority = {
        "downstream_context": 4,
        "content_profile_final": 3,
        "content_profile": 2,
        "content_profile_draft": 1,
    }
    profile_artifacts = [
        artifact
        for artifact in artifacts or []
        if priority.get(str(artifact.artifact_type or "").strip(), 0) > 0
    ]
    if not profile_artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    latest_final = max(
        (artifact for artifact in profile_artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    latest_downstream = max(
        (artifact for artifact in profile_artifacts if str(artifact.artifact_type or "").strip() == "downstream_context"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    if latest_final is not None and (
        latest_downstream is None
        or (latest_final.created_at or epoch) > (latest_downstream.created_at or epoch)
    ):
        return latest_final
    return max(
        profile_artifacts,
        key=lambda artifact: (
            priority.get(str(artifact.artifact_type or "").strip(), 0),
            artifact.created_at or epoch,
            str(artifact.id),
        ),
    )


async def _load_manual_editor_base_video_summary(session: AsyncSession, *, job_id: uuid.UUID) -> str | None:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(list(_DOWNSTREAM_PROFILE_ARTIFACT_TYPES)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifact = _select_preferred_downstream_artifact(result.scalars().all())
    profile = resolve_downstream_profile(artifact.data_json if artifact and isinstance(artifact.data_json, dict) else {})
    return _normalize_manual_video_summary(profile.get("summary"))


def _apply_manual_video_summary_to_profile(
    profile: dict[str, Any] | None,
    *,
    video_summary: str,
    updated_at: str,
) -> dict[str, Any]:
    next_profile = dict(profile or {})
    resolved_feedback = (
        dict(next_profile.get("resolved_review_user_feedback") or {})
        if isinstance(next_profile.get("resolved_review_user_feedback"), dict)
        else {}
    )
    user_feedback = (
        dict(next_profile.get("user_feedback") or {})
        if isinstance(next_profile.get("user_feedback"), dict)
        else {}
    )
    manual_evidence = (
        dict(next_profile.get("manual_evidence") or {})
        if isinstance(next_profile.get("manual_evidence"), dict)
        else {}
    )
    manual_evidence["video_summary"] = {
        "value": video_summary,
        "source": "manual_editor",
        "strength": "strong",
        "updated_at": updated_at,
    }
    next_profile.update(
        {
            "summary": video_summary,
            "manual_video_summary": video_summary,
            "manual_evidence": manual_evidence,
            "resolved_review_user_feedback": {**resolved_feedback, "summary": video_summary},
            "user_feedback": {**user_feedback, "summary": video_summary},
            "review_mode": "manual_confirmed",
        }
    )
    return next_profile


async def _persist_manual_video_summary_evidence(
    session: AsyncSession,
    *,
    job: Job,
    video_summary: str | None,
    updated_at: str,
) -> bool:
    normalized_summary = _normalize_manual_video_summary(video_summary)
    if not normalized_summary:
        return False
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job.id,
            Artifact.artifact_type.in_(list(_DOWNSTREAM_PROFILE_ARTIFACT_TYPES)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts = result.scalars().all()
    selected = _select_preferred_downstream_artifact(artifacts)
    base_profile = resolve_downstream_profile(selected.data_json if selected and isinstance(selected.data_json, dict) else {})
    existing_evidence = base_profile.get("manual_evidence") if isinstance(base_profile.get("manual_evidence"), dict) else {}
    existing_summary_evidence = existing_evidence.get("video_summary") if isinstance(existing_evidence, dict) else {}
    if (
        str(base_profile.get("summary") or "").strip() == normalized_summary
        and isinstance(existing_summary_evidence, dict)
        and str(existing_summary_evidence.get("source") or "").strip() == "manual_editor"
        and str(existing_summary_evidence.get("value") or "").strip() == normalized_summary
    ):
        return False

    profile = _apply_manual_video_summary_to_profile(
        base_profile,
        video_summary=normalized_summary,
        updated_at=updated_at,
    )
    profile = strip_publication_only_profile_fields(profile)
    step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
    )
    review_step = step_result.scalar_one_or_none()
    session.add(
        Artifact(
            job_id=job.id,
            step_id=review_step.id if review_step else None,
            artifact_type="content_profile_final",
            data_json=profile,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            step_id=review_step.id if review_step else None,
            artifact_type="downstream_context",
            data_json=build_downstream_context(profile),
        )
    )
    job.content_summary = normalized_summary
    return True


async def _persist_manual_video_summary_source_context(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    video_summary: str | None,
    updated_at: str,
) -> None:
    normalized_summary = _normalize_manual_video_summary(video_summary)
    if not normalized_summary:
        return
    step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "content_profile")
    )
    step = step_result.scalar_one_or_none()
    if step is None:
        return
    metadata = dict(step.metadata_ or {}) if isinstance(step.metadata_, dict) else {}
    source_context = dict(metadata.get("source_context") or {}) if isinstance(metadata.get("source_context"), dict) else {}
    source_context.update(
        {
            "manual_video_summary": normalized_summary,
            "manual_video_summary_source": "manual_editor",
            "manual_video_summary_strength": "strong",
            "manual_video_summary_updated_at": updated_at,
        }
    )
    metadata["source_context"] = source_context
    step.metadata_ = metadata


async def _load_content_profile_review_evidence(
    job_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    evidence_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(["content_profile_ocr", "transcript_evidence", "entity_resolution_trace"]),
        )
        .order_by(Artifact.created_at.desc())
    )
    evidence_artifacts = evidence_result.scalars().all()
    ocr_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "content_profile_ocr"),
        None,
    )
    transcript_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "transcript_evidence"),
        None,
    )
    entity_resolution_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "entity_resolution_trace"),
        None,
    )
    return {
        "ocr_evidence": _coerce_artifact_payload(ocr_artifact),
        "transcript_evidence": _coerce_artifact_payload(transcript_artifact),
        "entity_resolution_trace": _coerce_artifact_payload(entity_resolution_artifact),
    }


async def _build_current_reviewed_subtitle_excerpt(
    job_id: uuid.UUID,
    session: AsyncSession,
) -> str:
    subtitle_item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_items = subtitle_item_result.scalars().all()
    if not subtitle_items:
        return ""

    correction_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
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
        for correction in correction_result.scalars().all()
        if correction.human_decision == "accepted"
    ]
    return build_reviewed_transcript_excerpt(
        [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ],
        accepted_corrections,
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    include_history: bool = False,
    session: AsyncSession = Depends(get_session),
):
    page_limit = max(1, min(int(limit or 50), 200))
    page_offset = max(0, int(offset or 0))
    raw_limit = page_limit
    raw_offset = page_offset
    if not include_history:
        # The primary queue collapses duplicate reruns into one visible card.
        # Fetch a larger raw window and apply offset after collapse; otherwise
        # the first page can shrink to only a few cards when recent duplicate
        # runs dominate the raw ordering.
        raw_limit = max(page_limit + page_offset, page_limit * 8)
        raw_offset = 0
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.publication_attempts), selectinload(Job.creator_card))
        .order_by(Job.updated_at.desc(), Job.created_at.desc())
        .limit(raw_limit)
        .offset(raw_offset)
    )
    jobs = result.scalars().all()
    if jobs:
        job_ids = [job.id for job in jobs]
        artifact_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id.in_(job_ids),
                Artifact.artifact_type.in_(_LIST_PREVIEW_ARTIFACT_TYPES),
            )
            .order_by(Artifact.job_id.asc(), Artifact.created_at.desc(), Artifact.id.desc())
        )
        artifacts_by_job: dict[uuid.UUID, list[Artifact]] = {}
        for artifact in artifact_result.scalars().all():
            artifacts_by_job.setdefault(artifact.job_id, []).append(artifact)
        for job in jobs:
            set_committed_value(job, "artifacts", artifacts_by_job.get(job.id, []))
    _attach_job_previews(jobs, lightweight=True)
    if not include_history:
        jobs = _collapse_jobs_for_primary_queue(jobs)
        jobs = jobs[page_offset:page_offset + page_limit]
    return jobs


@router.get("/usage-summary", response_model=JobsUsageSummaryOut)
async def get_jobs_usage_summary(limit: int = 60, session: AsyncSession = Depends(get_session)):
    normalized_limit = max(1, min(int(limit or 60), 500))
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.updated_at.desc())
        .limit(normalized_limit)
    )
    jobs = result.scalars().all()
    summary = build_jobs_usage_summary(jobs, step_labels=STEP_LABELS)
    return JobsUsageSummaryOut(
        job_count=int(summary.get("job_count") or 0),
        jobs_with_telemetry=int(summary.get("jobs_with_telemetry") or 0),
        total_calls=int(summary.get("total_calls") or 0),
        total_prompt_tokens=int(summary.get("total_prompt_tokens") or 0),
        total_completion_tokens=int(summary.get("total_completion_tokens") or 0),
        total_tokens=int(summary.get("total_tokens") or 0),
        cache=dict(summary.get("cache") or {}),
        top_steps=list(summary.get("top_steps") or []),
        top_models=list(summary.get("top_models") or []),
        top_providers=list(summary.get("top_providers") or []),
    )


@router.get("/usage-trend", response_model=JobsUsageTrendOut)
async def get_jobs_usage_trend(
    days: int = 7,
    limit: int = 120,
    focus_type: str | None = None,
    focus_name: str | None = None,
    step_name: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    normalized_limit = max(1, min(int(limit or 120), 500))
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.updated_at.desc())
        .limit(normalized_limit)
    )
    jobs = result.scalars().all()
    trend = build_jobs_usage_trend(
        jobs,
        days=days,
        step_labels=STEP_LABELS,
        focus_type=focus_type,
        focus_name=focus_name,
        step_name=step_name,
    )
    return JobsUsageTrendOut(
        days=int(trend.get("days") or 7),
        focus_type=trend.get("focus_type"),
        focus_name=trend.get("focus_name"),
        points=list(trend.get("points") or []),
    )


DEFAULT_REMIX_PRODUCTION_MANIFEST_ENV = "ROUGHCUT_REMIX_PRODUCTION_MANIFEST"
REMIX_PRODUCTION_WORKFLOW_MODES = {"remix_auto_commentary", "remix_llm_plan", "script_footage_remix"}
REMIX_PRODUCTION_STEP_NAME = "script_footage_remix"
REMIX_PRODUCTION_TTS_TIMEOUT_SEC = 3600.0
REMIX_PRODUCTION_STARTUP_RECOVERY_MAX_ATTEMPTS = 3
REMIX_PRODUCTION_CELERY_TASK_NAME = "roughcut.pipeline.tasks.remix_production_run"
REMIX_PRODUCTION_CELERY_QUEUE = "media_queue"
_PUBLICATION_COVER_AUTO_HEAL_BLOCK_TOKENS = (
    "封面",
    "cover",
    "codex",
    "imagegen",
    "位图",
    "bitmap",
)


class RemixProductionStartOut(BaseModel):
    job_id: str
    status: str
    detail: str
    command: list[str] = Field(default_factory=list)
    task_id: str | None = None


class RemixProductionTaskCreateIn(BaseModel):
    season: int
    episode: int
    manifest_path: str | None = None


@router.get("/remix-production/tasks")
async def list_remix_production_tasks(
    manifest_path: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    path, payload = _load_remix_production_manifest(manifest_path)
    tasks = _remix_manifest_tasks(payload)
    existing_jobs = await _find_remix_production_jobs_for_tasks(session, tasks)
    tasks = [_attach_remix_task_job_state(task, existing_jobs.get(_remix_task_identity(task))) for task in tasks]
    pending_tasks = [item for item in tasks if str(item.get("status") or "") == "pending"]
    blocked_missing_script_tasks = [item for item in tasks if str(item.get("status") or "") == "blocked_missing_script"]
    completed_by_user = [dict(item) for item in list(payload.get("completed_by_user") or []) if isinstance(item, dict)]
    pending_file_missing_count = 0
    for task in pending_tasks:
        for key in ("script_path", "source_video_path"):
            value = str(task.get(key) or "").strip()
            if value and not _remix_manifest_path_exists(value):
                pending_file_missing_count += 1
    return {
        "schema": str(payload.get("schema") or "roughcut.remix.production_tasks.v1"),
        "id": str(payload.get("id") or path.stem),
        "manifest_path": str(path),
        "creator_profile": str(payload.get("creator_profile") or ""),
        "task_binding_id": str(payload.get("task_binding_id") or ""),
        "source_root": str(payload.get("source_root") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "selection_policy": dict(payload.get("selection_policy") or {}),
        "execution": dict(payload.get("execution") or {}),
        "summary": {
            "task_count": len(tasks),
            "pending_count": len(pending_tasks),
            "blocked_missing_script_count": len(blocked_missing_script_tasks),
            "completed_by_user_count": len(completed_by_user),
            "pending_file_missing_count": pending_file_missing_count,
        },
        "completed_by_user": completed_by_user,
        "pending_tasks": pending_tasks,
        "blocked_missing_script_tasks": blocked_missing_script_tasks,
        "tasks": tasks,
    }


@router.post("/remix-production/tasks/job", response_model=JobOut)
async def create_remix_production_task_job(
    request: RemixProductionTaskCreateIn,
    session: AsyncSession = Depends(get_session),
):
    _, payload = _load_remix_production_manifest(request.manifest_path)
    task = _find_remix_manifest_task(payload, season=request.season, episode=request.episode)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Remix production task not found: S{request.season:02d}E{request.episode:02d}")
    if str(task.get("status") or "") != "pending":
        raise HTTPException(status_code=422, detail="Only pending remix production tasks can be added to the task queue")
    job = await _create_or_update_remix_production_job(session, payload, task)
    await session.commit()
    await session.refresh(job)
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.artifacts), selectinload(Job.render_outputs), selectinload(Job.publication_attempts))
        .where(Job.id == job.id)
    )
    created_job = result.scalar_one()
    _attach_job_previews([created_job])
    return created_job


@router.post("/remix-production/jobs/{job_id}/start", response_model=RemixProductionStartOut)
async def start_remix_production_job(
    job_id: uuid.UUID,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id, options=[selectinload(Job.steps)])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _job_is_remix_production(job):
        raise HTTPException(status_code=422, detail="Job is not a script-footage remix production task")
    if str(job.status or "").strip() in {"processing", "running"}:
        raise HTTPException(status_code=409, detail="Remix production job is already running")

    source_context = _extract_job_source_context_from_steps(job.steps or [])
    remix_payload = source_context.get("remix_production") if isinstance(source_context, dict) else None
    if not isinstance(remix_payload, dict):
        raise HTTPException(status_code=422, detail="Remix production metadata is missing")
    runtime_blocker = _remix_runtime_path_blocker(remix_payload)
    if runtime_blocker:
        raise HTTPException(status_code=422, detail=runtime_blocker)
    command, output_dir = _build_remix_production_job_command(job, remix_payload, force=force)
    step = _ensure_remix_production_step(job)
    now = datetime.now(timezone.utc)
    task_id = uuid.uuid4().hex
    step.status = "running"
    step.started_at = now
    step.finished_at = None
    step.error_message = None
    step.attempt += 1
    step.metadata_ = {
        **(step.metadata_ or {}),
        "command": command,
        "output_dir": str(output_dir),
        "progress": 0.05,
        "detail": "已提交解说二创 script-footage 生产任务。",
        "task_id": task_id,
        "queue": REMIX_PRODUCTION_CELERY_QUEUE,
        "dispatched_at": now.isoformat(),
        "worker_started_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    job.status = "processing"
    job.error_message = None
    job.updated_at = now
    await session.commit()
    try:
        _send_remix_production_job_task(str(job.id), command, str(output_dir), task_id=task_id)
    except Exception as exc:
        detail = f"解说二创生产任务入队失败：{exc}"
        now = datetime.now(timezone.utc)
        step.status = "failed"
        step.finished_at = now
        step.error_message = detail
        step.metadata_ = {
            **(step.metadata_ or {}),
            "detail": detail,
            "updated_at": now.isoformat(),
        }
        job.status = "failed"
        job.error_message = detail
        job.updated_at = now
        await session.commit()
        raise HTTPException(status_code=503, detail=detail) from exc
    return RemixProductionStartOut(
        job_id=str(job.id),
        status="started",
        detail="已将该集解说二创生产任务提交到媒体队列。",
        command=command,
        task_id=task_id,
    )


def _resolve_remix_production_manifest_path(value: str | None) -> Path:
    raw = str(value or os.getenv(DEFAULT_REMIX_PRODUCTION_MANIFEST_ENV) or "").strip()
    if not raw:
        discovered = _discover_default_remix_production_manifest_path()
        if discovered is not None:
            return discovered
        raise HTTPException(
            status_code=400,
            detail=f"Remix production manifest path is required. Set {DEFAULT_REMIX_PRODUCTION_MANIFEST_ENV} or pass a manifest path.",
        )
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (DEFAULT_PROJECT_ROOT / path).resolve()


def _discover_default_remix_production_manifest_path() -> Path | None:
    candidates: list[Path] = []
    profiles_dir = DEFAULT_PROJECT_ROOT / "data" / "creator_profiles"
    for profile_path in sorted(profiles_dir.glob("*.json")) if profiles_dir.exists() else []:
        try:
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for binding in list(payload.get("remix_task_bindings") or []):
            if not isinstance(binding, dict):
                continue
            raw_path = str(binding.get("production_manifest_path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = (DEFAULT_PROJECT_ROOT / path).resolve()
            if path.exists() and path.is_file():
                candidates.append(path)

    manifest_dir = DEFAULT_PROJECT_ROOT / "data" / "remix_production_tasks"
    if manifest_dir.exists():
        candidates.extend(path.resolve() for path in manifest_dir.glob("*.json") if path.is_file())

    unique_candidates: dict[str, Path] = {str(path): path for path in candidates}
    if not unique_candidates:
        return None
    ranked = sorted(
        unique_candidates.values(),
        key=lambda path: (
            "example" in path.name.lower(),
            -path.stat().st_mtime,
            path.name.lower(),
        ),
    )
    return ranked[0]


def _load_remix_production_manifest(value: str | None) -> tuple[Path, dict[str, Any]]:
    path = _resolve_remix_production_manifest_path(value)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Remix production manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid remix production manifest JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Remix production manifest must be a JSON object")
    payload["_manifest_path"] = str(path)
    return path, payload


def _remix_manifest_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(payload.get("tasks") or []) if isinstance(item, dict)]


def _find_remix_manifest_task(payload: dict[str, Any], *, season: int, episode: int) -> dict[str, Any] | None:
    for task in _remix_manifest_tasks(payload):
        if int(task.get("season") or 0) == int(season) and int(task.get("episode") or 0) == int(episode):
            return task
    return None


def _remix_task_identity(task: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(task.get("source_video_path") or "").strip().lower(),
        int(task.get("season") or 0),
        int(task.get("episode") or 0),
        str(task.get("title") or "").strip().lower(),
    )


def _remix_task_label(task: dict[str, Any]) -> str:
    season = int(task.get("season") or 0)
    episode = int(task.get("episode") or 0)
    title = str(task.get("title") or "").strip() or f"E{episode:02d}"
    return f"S{season:02d}E{episode:02d} · {title}"


def _job_is_remix_production(job: Job) -> bool:
    workflow_mode = str(getattr(job, "workflow_mode", "") or "").strip()
    if workflow_mode in REMIX_PRODUCTION_WORKFLOW_MODES:
        return True
    source_context = _extract_job_source_context_from_steps(list(getattr(job, "steps", None) or []))
    return isinstance(source_context.get("remix_production"), dict)


def _attach_remix_task_job_state(task: dict[str, Any], job: Job | None) -> dict[str, Any]:
    item = dict(task)
    if job is None:
        return item
    item["job_id"] = str(job.id)
    item["job_status"] = str(job.status or "")
    item["job_updated_at"] = _iso_or_none(job.updated_at)
    progress_percent = _calculate_job_progress_percent(job)
    item["job_progress_percent"] = progress_percent
    item["progress_percent"] = progress_percent
    output_path = _latest_remix_job_output_path(job)
    if output_path:
        item["output_path"] = output_path
    return item


async def _find_remix_production_jobs_for_tasks(
    session: AsyncSession,
    tasks: list[dict[str, Any]],
) -> dict[tuple[str, int, int, str], Job]:
    source_paths = [str(task.get("source_video_path") or "").strip() for task in tasks if str(task.get("source_video_path") or "").strip()]
    if not source_paths:
        return {}
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.artifacts), selectinload(Job.render_outputs), selectinload(Job.publication_attempts))
        .where(Job.source_path.in_(source_paths), Job.workflow_mode.in_(REMIX_PRODUCTION_WORKFLOW_MODES))
        .order_by(Job.updated_at.desc())
    )
    jobs_by_source: dict[str, Job] = {}
    for job in result.scalars().all():
        jobs_by_source.setdefault(str(job.source_path or "").strip().lower(), job)
    return {
        _remix_task_identity(task): jobs_by_source[str(task.get("source_video_path") or "").strip().lower()]
        for task in tasks
        if str(task.get("source_video_path") or "").strip().lower() in jobs_by_source
    }


async def _resolve_remix_creator_card_id(session: AsyncSession, payload: dict[str, Any]) -> uuid.UUID | None:
    profile_slug = str(payload.get("creator_profile") or "").strip()
    profile: dict[str, Any] = {}
    if profile_slug:
        profile_path = DEFAULT_PROJECT_ROOT / "data" / "creator_profiles" / f"{profile_slug}.json"
        if profile_path.exists():
            try:
                loaded = json.loads(profile_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    profile = loaded
            except json.JSONDecodeError:
                profile = {}
    card_payload = profile.get("creator_card_compatible") if isinstance(profile.get("creator_card_compatible"), dict) else {}
    name = str(card_payload.get("name") or profile.get("name") or profile_slug).strip()
    if not name:
        return None
    result = await session.execute(select(CreatorCard).where(CreatorCard.name == name).order_by(CreatorCard.updated_at.desc()))
    existing = result.scalars().first()
    if existing is not None:
        return existing.id
    card = CreatorCard(
        name=name,
        positioning=str(card_payload.get("positioning") or profile.get("positioning") or "").strip() or None,
        content_domains=list(card_payload.get("content_domains") or profile.get("content_domains") or []),
        audience=str(card_payload.get("audience") or profile.get("audience") or "").strip() or None,
        default_platforms=list(card_payload.get("default_platforms") or profile.get("default_platforms") or []),
        natural_language_profile=str(profile.get("natural_language_profile") or "").strip() or None,
        status="active",
    )
    session.add(card)
    await session.flush()
    return card.id


async def _create_or_update_remix_production_job(
    session: AsyncSession,
    payload: dict[str, Any],
    task: dict[str, Any],
) -> Job:
    existing = await _find_remix_production_jobs_for_tasks(session, [task])
    creator_card_id = await _resolve_remix_creator_card_id(session, payload)
    existing_job = existing.get(_remix_task_identity(task))
    if existing_job is not None:
        _refresh_remix_production_job_metadata(existing_job, payload, task, creator_card_id=creator_card_id)
        _ensure_remix_production_cover_artifact(existing_job, payload, task)
        return existing_job

    source_video_path = str(task.get("source_video_path") or "").strip()
    script_path = str(task.get("script_path") or "").strip()
    if not source_video_path or not script_path:
        raise HTTPException(status_code=422, detail="Remix production task is missing source video or script path")

    label = _remix_task_label(task)
    source_context = _build_remix_production_source_context(payload, task)
    job = Job(
        id=uuid.uuid4(),
        source_path=source_video_path,
        source_name=label,
        file_hash=_remix_production_file_hash(payload, task),
        status="pending",
        language="zh-CN",
        workflow_template=None,
        job_flow_mode="auto",
        workflow_mode="script_footage_remix",
        enhancement_modes=["ai_effects"],
        output_dir=str(_default_remix_production_output_dir(payload, task)),
        creator_card_id=creator_card_id,
        task_brief=(
            f"{label} 解说二创正式生产任务。完整保留文案，使用创作者参考语音、"
            "Source-ASR 定位原片剧情，TTS-ASR 对齐字幕，Hyperframes 包装。"
        ),
        execution_mode="auto",
        platform_targets_json=[],
    )
    session.add(job)
    await session.flush()
    session.add(
        JobStep(
            job_id=job.id,
            step_name="content_profile",
            status="done",
            metadata_={"source_context": source_context, "detail": "二创生产任务元数据已导入。"},
        )
    )
    session.add(
        JobStep(
            job_id=job.id,
            step_name=REMIX_PRODUCTION_STEP_NAME,
            status="pending",
            metadata_={"source_context": source_context, "detail": "等待启动解说二创生产。", "progress": 0.0},
        )
    )
    _ensure_remix_production_cover_artifact(job, payload, task)
    await _ensure_job_agent_plan(session, job)
    return job


def _refresh_remix_production_job_metadata(
    job: Job,
    payload: dict[str, Any],
    task: dict[str, Any],
    *,
    creator_card_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    source_video_path = str(task.get("source_video_path") or "").strip()
    script_path = str(task.get("script_path") or "").strip()
    if not source_video_path or not script_path:
        raise HTTPException(status_code=422, detail="Remix production task is missing source video or script path")

    label = _remix_task_label(task)
    source_context = _build_remix_production_source_context(payload, task)
    job.source_path = source_video_path
    job.source_name = label
    job.file_hash = _remix_production_file_hash(payload, task)
    job.workflow_mode = "script_footage_remix"
    job.output_dir = str(_default_remix_production_output_dir(payload, task))
    if creator_card_id is not None:
        job.creator_card_id = creator_card_id
    job.task_brief = (
        f"{label} 解说二创正式生产任务。完整保留文案，使用创作者参考语音、"
        "Source-ASR 定位原片剧情，TTS-ASR 对齐字幕，Hyperframes 包装。"
    )

    steps = list(job.steps or [])
    content_step = _find_step(steps, "content_profile")
    if content_step is None:
        content_step = JobStep(job_id=job.id, step_name="content_profile", status="done")
        (job.steps or []).append(content_step)
    content_step.status = "done"
    content_step.error_message = None
    content_step.metadata_ = {
        **(content_step.metadata_ or {}),
        "source_context": source_context,
        "detail": "二创生产任务元数据已导入。",
    }

    remix_step = _find_step(steps, REMIX_PRODUCTION_STEP_NAME)
    if remix_step is None:
        remix_step = JobStep(job_id=job.id, step_name=REMIX_PRODUCTION_STEP_NAME, status="pending")
        (job.steps or []).append(remix_step)
    remix_step.metadata_ = {
        **(remix_step.metadata_ or {}),
        "source_context": source_context,
        "detail": (remix_step.metadata_ or {}).get("detail") or "等待启动解说二创生产。",
        "progress": (remix_step.metadata_ or {}).get("progress", 0.0),
    }
    return source_context


def _build_remix_production_source_context(payload: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    label = _remix_task_label(task)
    script_path = str(task.get("script_path") or "").strip()
    source_video_path = str(task.get("source_video_path") or "").strip()
    manifest_path = str(payload.get("_manifest_path") or "").strip()
    source_root = str(payload.get("source_root") or "").strip()
    creator_profile = str(payload.get("creator_profile") or "").strip()
    return {
        "source_name": label,
        "video_description": f"文案：{script_path}\n原片：{source_video_path}",
        "queue_task_kind": "remix_production",
        "remix_production": {
            "manifest_path": manifest_path,
            "manifest_id": str(payload.get("id") or "").strip(),
            "task_binding_id": str(payload.get("task_binding_id") or "").strip(),
            "source_root": source_root,
            "creator_profile": creator_profile,
            "season": int(task.get("season") or 0),
            "episode": int(task.get("episode") or 0),
            "title": str(task.get("title") or "").strip(),
            "script_path": script_path,
            "source_video_path": source_video_path,
            "script_policy": str((payload.get("selection_policy") or {}).get("script_policy") or "preserve_full_script"),
            "duration_policy": str((payload.get("selection_policy") or {}).get("duration_policy") or "duration_is_warning_not_script_cut"),
        },
    }


def _remix_production_file_hash(payload: dict[str, Any], task: dict[str, Any]) -> str:
    source = "|".join(
        [
            "remix_production",
            str(payload.get("id") or ""),
            str(task.get("season") or ""),
            str(task.get("episode") or ""),
            str(task.get("source_video_path") or ""),
            str(task.get("script_path") or ""),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _default_remix_production_output_dir(payload: dict[str, Any], task: dict[str, Any]) -> Path:
    task_binding = re.sub(r"[^A-Za-z0-9._-]+", "_", str(payload.get("task_binding_id") or "script_footage_remix")).strip("._-")
    episode = int(task.get("episode") or 0)
    output_root = Path(str(getattr(get_settings(), "output_dir", "") or "")).expanduser()
    if not str(output_root).strip():
        output_root = DEFAULT_PROJECT_ROOT / "data" / "output"
    return output_root / "script-footage-remix-production" / (task_binding or "script_footage_remix") / f"s02e{episode:02d}"


def _remix_production_thumbnail_path(payload: dict[str, Any], task: dict[str, Any]) -> Path:
    manifest_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(payload.get("id") or "script_footage_remix")).strip("._-")
    episode = int(task.get("episode") or 0)
    return DEFAULT_PROJECT_ROOT / "data" / "remix-production-thumbnails" / (manifest_id or "script_footage_remix") / f"s02e{episode:02d}.jpg"


def _resolve_remix_production_output_cover_path(output_dir: Path, *, episode: int) -> Path | None:
    candidate_patterns = [
        f"s02e{episode:02d}_*_cover.jpg",
        f"s02e{episode:02d}_*/s02e{episode:02d}_*_cover.jpg",
    ]
    for pattern in candidate_patterns:
        for cover_path in sorted(output_dir.glob(pattern)):
            if cover_path.is_file():
                return cover_path
    return None


def _resolve_remix_production_cover_path(payload: dict[str, Any], task: dict[str, Any]) -> Path | None:
    thumbnail_path = _remix_production_thumbnail_path(payload, task)
    if thumbnail_path.exists():
        return thumbnail_path

    episode = int(task.get("episode") or 0)
    output_dir = _default_remix_production_output_dir(payload, task)
    return _resolve_remix_production_output_cover_path(output_dir, episode=episode)


def _ensure_remix_production_cover_artifact(job: Job, payload: dict[str, Any], task: dict[str, Any]) -> None:
    cover_path = _resolve_remix_production_cover_path(payload, task)
    if cover_path is None:
        return
    cover_text = str(cover_path)
    for artifact in list(getattr(job, "artifacts", None) or []):
        if str(getattr(artifact, "artifact_type", "") or "") != "render_outputs":
            continue
        data = dict(getattr(artifact, "data_json", None) or {})
        if _normalize_existing_image_path(data.get("cover")) is None:
            data["cover"] = cover_text
        data.setdefault("cover_source", "remix_production")
        artifact.data_json = data
        return
    job.artifacts.append(
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={"cover": cover_text, "cover_source": "remix_production"},
        )
    )


def _ensure_remix_production_step(job: Job) -> JobStep:
    for step in list(job.steps or []):
        if step.step_name == REMIX_PRODUCTION_STEP_NAME:
            return step
    step = JobStep(job_id=job.id, step_name=REMIX_PRODUCTION_STEP_NAME, status="pending")
    job.steps.append(step)
    return step


def _remix_portable_path(value: str) -> str:
    normalized = str(value or "").strip().strip('"').replace("\\", "/")
    normalized = re.sub(r"/{2,}", "/", normalized)
    normalized = re.sub(r"^([A-Za-z]:)/*", r"\1/", normalized)
    return normalized.rstrip("/")


def _remix_source_runtime_path(value: str) -> str:
    raw = str(value or "").strip().strip('"')
    if not raw:
        return raw

    host_root = _remix_portable_path(os.getenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", ""))
    container_root = _remix_portable_path(os.getenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", "/app/remix-source")) or "/app/remix-source"
    if host_root:
        raw_portable = _remix_portable_path(raw)
        raw_key = raw_portable.casefold()
        host_key = host_root.casefold()
        if raw_key == host_key:
            return container_root
        if raw_key.startswith(f"{host_key}/"):
            relative = raw_portable[len(host_root):].lstrip("/")
            return str(Path(container_root, *[part for part in relative.split("/") if part]))
    try:
        if Path(raw).exists():
            return raw
    except OSError:
        pass
    return raw


def _remix_internal_api_base() -> str:
    explicit = str(os.getenv("ROUGHCUT_REMIX_API_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    internal_port = str(os.getenv("ROUGHCUT_API_INTERNAL_PORT") or "8000").strip() or "8000"
    return f"http://127.0.0.1:{internal_port}"


def _remix_qwen3_asr_base() -> str:
    return str(
        os.getenv("ROUGHCUT_REMIX_QWEN3_ASR_BASE_URL")
        or os.getenv("LOCAL_ASR_API_BASE_URL")
        or os.getenv("ROUGHCUT_DOCKER_LOCAL_ASR_API_BASE_URL")
        or "http://127.0.0.1:30230"
    ).strip().rstrip("/")


def _remix_job_output_dir(job: Job, remix_payload: dict[str, Any], *, episode: int) -> Path:
    default_output_dir = _default_remix_production_output_dir(
        {"task_binding_id": remix_payload.get("task_binding_id")},
        {"episode": episode},
    )
    raw_output_dir = str(job.output_dir or "").strip()
    if not raw_output_dir:
        job.output_dir = str(default_output_dir)
        return default_output_dir

    legacy_root = _remix_portable_path(str(DEFAULT_PROJECT_ROOT / "output"))
    raw_key = _remix_portable_path(raw_output_dir)
    if raw_key == legacy_root or raw_key.startswith(f"{legacy_root}/"):
        job.output_dir = str(default_output_dir)
        return default_output_dir
    return Path(raw_output_dir).expanduser()


def _build_remix_production_job_command(job: Job, remix_payload: dict[str, Any], *, force: bool) -> tuple[list[str], Path]:
    source_root = str(remix_payload.get("source_root") or "").strip()
    if not source_root:
        source_path = Path(str(remix_payload.get("script_path") or "")).expanduser()
        source_root = str(source_path.parent) if source_path.parent else ""
    source_root = _remix_source_runtime_path(source_root)
    episode = int(remix_payload.get("episode") or 0)
    creator_profile = str(remix_payload.get("creator_profile") or "").strip()
    output_dir = _remix_job_output_dir(job, remix_payload, episode=episode)
    command = [
        sys.executable,
        "-m",
        "roughcut.cli",
        "remix",
        "script-footage",
        "--source-root",
        source_root,
        "--episodes",
        str(episode),
        "--output-dir",
        str(output_dir),
        "--api-base",
        _remix_internal_api_base(),
        "--qwen3-asr-base",
        _remix_qwen3_asr_base(),
        "--creator-profile",
        creator_profile,
        "--tts-timeout-sec",
        str(REMIX_PRODUCTION_TTS_TIMEOUT_SEC),
    ]
    if force:
        command.append("--force")
        command.append("--force-tts")
    return command, output_dir


def _remix_runtime_path_blocker(remix_payload: dict[str, Any]) -> str | None:
    candidates = {
        "source_root": str(remix_payload.get("source_root") or "").strip(),
        "source_video_path": str(remix_payload.get("source_video_path") or "").strip(),
        "script_path": str(remix_payload.get("script_path") or "").strip(),
    }
    missing: list[str] = []
    for label, value in candidates.items():
        if not value:
            continue
        runtime_value = _remix_source_runtime_path(value)
        try:
            if not Path(runtime_value).exists():
                if runtime_value != value:
                    missing.append(f"{label}={value} -> {runtime_value}")
                else:
                    missing.append(f"{label}={value}")
        except OSError:
            missing.append(f"{label}={value}")
    if not missing:
        return None
    return (
        "解说二创生产源素材在当前 API 运行环境中不可读。请把源片/文案目录挂载进 API 容器，"
        "或设置 ROUGHCUT_REMIX_SOURCE_HOST_ROOT/ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT 后重建 API 容器。缺失路径："
        + "；".join(missing)
    )


def _run_remix_production_job_background(job_id: str, command: list[str], output_dir: str) -> None:
    asyncio.run(_run_remix_production_job(job_id, command, output_dir))


def _send_remix_production_job_task(job_id: str, command: list[str], output_dir: str, *, task_id: str) -> object:
    return celery_app.send_task(
        REMIX_PRODUCTION_CELERY_TASK_NAME,
        args=[job_id, command, output_dir],
        queue=REMIX_PRODUCTION_CELERY_QUEUE,
        task_id=task_id,
    )


async def recover_interrupted_remix_production_jobs_on_startup(
    *,
    schedule_task: Callable[[str, list[str], str, str], object] | None = None,
) -> int:
    settings = get_settings()
    if not bool(getattr(settings, "startup_recovery_enabled", True)):
        return 0

    scheduled_runs: list[tuple[str, list[str], str, str]] = []
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job)
            .options(selectinload(Job.steps))
            .where(
                Job.status.in_(["processing", "running"]),
                Job.workflow_mode.in_(REMIX_PRODUCTION_WORKFLOW_MODES),
            )
            .with_for_update(skip_locked=True)
        )
        jobs = result.scalars().unique().all()
        now = datetime.now(timezone.utc)
        for job in jobs:
            step = _find_step(list(job.steps or []), REMIX_PRODUCTION_STEP_NAME)
            if step is None or str(step.status or "").strip().lower() != "running":
                continue
            source_context = _extract_job_source_context_from_steps(job.steps or [])
            remix_payload = source_context.get("remix_production") if isinstance(source_context, dict) else None
            metadata = dict(step.metadata_ or {})
            if not isinstance(remix_payload, dict):
                detail = "服务启动恢复失败：解说二创任务缺少 remix production 元数据，无法自动续跑。"
                step.status = "failed"
                step.finished_at = now
                step.error_message = detail
                step.metadata_ = {**metadata, "detail": detail, "updated_at": now.isoformat()}
                job.status = "failed"
                job.error_message = detail
                job.updated_at = now
                continue
            if int(step.attempt or 0) >= REMIX_PRODUCTION_STARTUP_RECOVERY_MAX_ATTEMPTS:
                detail = (
                    "服务启动发现解说二创任务已达到最大自动恢复次数"
                    f"({REMIX_PRODUCTION_STARTUP_RECOVERY_MAX_ATTEMPTS})，不再自动续跑。"
                )
                step.status = "failed"
                step.finished_at = now
                step.error_message = detail
                step.metadata_ = {**metadata, "detail": detail, "updated_at": now.isoformat()}
                job.status = "failed"
                job.error_message = detail
                job.updated_at = now
                continue
            runtime_blocker = _remix_runtime_path_blocker(remix_payload)
            if runtime_blocker:
                detail = f"服务启动恢复失败：{runtime_blocker}"
                step.status = "failed"
                step.finished_at = now
                step.error_message = detail
                step.metadata_ = {**metadata, "detail": detail, "updated_at": now.isoformat()}
                job.status = "failed"
                job.error_message = detail
                job.updated_at = now
                continue

            command, output_dir = _build_remix_production_job_command(job, remix_payload, force=False)
            task_id = uuid.uuid4().hex
            step.status = "running"
            step.started_at = now
            step.finished_at = None
            step.error_message = None
            step.attempt = int(step.attempt or 0) + 1
            step.metadata_ = {
                **metadata,
                "command": command,
                "output_dir": str(output_dir),
                "progress": float(metadata.get("progress") or 0.05),
                "detail": "服务重启后自动恢复解说二创生产任务，复用已有中间产物继续执行。",
                "task_id": task_id,
                "queue": REMIX_PRODUCTION_CELERY_QUEUE,
                "startup_recovered_at": now.isoformat(),
                "dispatched_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            job.status = "processing"
            job.error_message = None
            job.updated_at = now
            scheduled_runs.append((str(job.id), command, str(output_dir), task_id))

        await session.commit()

    def _default_schedule(job_id: str, command: list[str], output_dir: str, task_id: str) -> None:
        _send_remix_production_job_task(job_id, command, output_dir, task_id=task_id)

    scheduler = schedule_task or _default_schedule
    scheduled_count = 0
    failed_schedules: list[tuple[str, str]] = []
    for job_id, command, output_dir, task_id in scheduled_runs:
        try:
            scheduler(job_id, command, output_dir, task_id)
        except Exception as exc:
            failed_schedules.append((job_id, str(exc)))
            logger.warning("Failed to enqueue recovered remix production job job=%s error=%s", job_id, exc)
            continue
        scheduled_count += 1
        logger.warning("Recovered interrupted remix production job on startup job=%s output_dir=%s", job_id, output_dir)

    if failed_schedules:
        failure_now = datetime.now(timezone.utc)
        failed_by_job = {job_id: error for job_id, error in failed_schedules}
        async with factory() as session:
            result = await session.execute(
                select(Job)
                .options(selectinload(Job.steps))
                .where(Job.id.in_([uuid.UUID(job_id) for job_id in failed_by_job]))
            )
            for job in result.scalars().unique().all():
                detail = f"服务启动恢复入队失败：{failed_by_job.get(str(job.id), 'unknown error')}"
                step = _find_step(list(job.steps or []), REMIX_PRODUCTION_STEP_NAME)
                if step is not None:
                    step.status = "failed"
                    step.finished_at = failure_now
                    step.error_message = detail
                    step.metadata_ = {**(step.metadata_ or {}), "detail": detail, "updated_at": failure_now.isoformat()}
                job.status = "failed"
                job.error_message = detail
                job.updated_at = failure_now
            await session.commit()
    return scheduled_count


async def _run_remix_production_job(job_id: str, command: list[str], output_dir: str) -> None:
    factory = get_session_factory()
    env = dict(os.environ)
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = f"{DEFAULT_PROJECT_ROOT / 'src'}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(DEFAULT_PROJECT_ROOT / "src")
    result = subprocess.run(
        command,
        cwd=DEFAULT_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id), options=[selectinload(Job.steps)])
        if job is None:
            return
        step = _ensure_remix_production_step(job)
        now = datetime.now(timezone.utc)
        metadata = dict(step.metadata_ or {})
        metadata.update({
            "command": command,
            "output_dir": output_dir,
            "returncode": result.returncode,
            "stdout_tail": (result.stdout or "")[-4000:],
            "stderr_tail": (result.stderr or "")[-4000:],
            "updated_at": now.isoformat(),
        })
        if result.returncode == 0:
            output_path = _resolve_remix_output_path(Path(output_dir))
            step.status = "done"
            step.finished_at = now
            step.error_message = None
            metadata["progress"] = 1.0
            metadata["detail"] = "解说二创生产完成。"
            job.status = "done"
            job.error_message = None
            if output_path:
                session.add(RenderOutput(job_id=job.id, output_path=output_path, status="done", progress=1.0))
                session.add(
                    Artifact(
                        job_id=job.id,
                        artifact_type="render_outputs",
                        data_json={
                            "packaged_mp4": output_path,
                            "output_path": output_path,
                            "script_footage_remix_report": str(Path(output_dir) / "script_footage_remix_sample_report.json"),
                        },
                    )
                )
        else:
            detail = (result.stderr or result.stdout or "解说二创生产失败").strip()[-1000:]
            step.status = "failed"
            step.finished_at = now
            step.error_message = detail
            metadata["progress"] = 0.0
            metadata["detail"] = detail
            job.status = "failed"
            job.error_message = detail
        step.metadata_ = metadata
        job.updated_at = now
        await session.commit()


def _resolve_remix_output_path(output_dir: Path) -> str | None:
    report_path = output_dir / "script_footage_remix_sample_report.json"
    if report_path.exists():
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            reports = payload.get("reports") if isinstance(payload, dict) else None
            if isinstance(reports, list) and reports:
                output_path = str((reports[0] or {}).get("output_path") or "").strip()
                if output_path:
                    return output_path
        except (OSError, json.JSONDecodeError):
            pass
    candidates = sorted(output_dir.glob("**/*_parenting_remix.mp4"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return str(candidates[0]) if candidates else None


def _latest_remix_job_output_path(job: Job) -> str | None:
    outputs = [
        str(getattr(item, "output_path", "") or "").strip()
        for item in list(getattr(job, "render_outputs", None) or [])
        if str(getattr(item, "output_path", "") or "").strip()
    ]
    if outputs:
        return outputs[0]
    for artifact in list(getattr(job, "artifacts", None) or []):
        if str(getattr(artifact, "artifact_type", "") or "") != "render_outputs":
            continue
        data = getattr(artifact, "data_json", None)
        if isinstance(data, dict):
            output = str(data.get("packaged_mp4") or data.get("output_path") or "").strip()
            if output:
                return output
    return None


def _remix_manifest_path_exists(value: str) -> bool:
    path_text = str(value or "").strip()
    if not path_text:
        return False
    if Path(path_text).exists():
        return True
    # SampleShow production manifests are authored on the Windows host. When the API
    # runs in Linux containers those drive-letter paths are valid for the host
    # CLI but cannot be resolved inside /app, so do not report them as missing.
    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", path_text):
        return True
    return False


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    language: str = Form("zh-CN"),
    workflow_template: str | None = Form(None),
    job_flow_mode: str | None = Form(None),
    workflow_mode: str | None = Form(None),
    enhancement_modes: list[str] | None = Form(None),
    creator_card_id: str | None = Form(None),
    task_brief: str | None = Form(None),
    execution_mode: str | None = Form(None),
    platform_targets: list[str] | None = Form(None),
    edit_mode: str | None = Form(None),
    automation_level: str | None = Form(None),
    material_usage: str | None = Form(None),
    smart_cut_rule_reasons: str | None = Form(None),
    material_enhancement_modes: str | None = Form(None),
    agent_capability_keys: str | None = Form(None),
    hyperframes_options: str | None = Form(None),
    translation_target_language: str | None = Form(None),
    start_mode: str | None = Form(None),
    output_dir: str | None = Form(None),
    video_description: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    uploaded_files = _normalize_uploaded_sources(file=file, files=files)
    if not uploaded_files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    try:
        language = normalize_job_language(language)
        workflow_template = normalize_workflow_template(workflow_template)
        execution_mode_explicit = execution_mode is not None and bool(str(execution_mode).strip())
        job_flow_mode = normalize_job_flow_mode(job_flow_mode)
        workflow_mode = normalize_workflow_mode(workflow_mode or settings.default_job_workflow_mode)
        output_dir = str(output_dir or "").strip() or None
        video_description = _normalize_video_description(video_description)
        task_brief = _normalize_video_description(task_brief)
        execution_mode = normalize_execution_mode(execution_mode)
        job_flow_mode = resolve_job_flow_mode_from_execution_mode(
            job_flow_mode,
            execution_mode,
            execution_mode_explicit=execution_mode_explicit,
        )
        parsed_creator_card_id = uuid.UUID(str(creator_card_id).strip()) if str(creator_card_id or "").strip() else None
        normalized_platform_targets = [str(item).strip() for item in list(platform_targets or []) if str(item).strip()]
        edit_mode = normalize_edit_mode(edit_mode)
        automation_level = normalize_automation_level(automation_level)
        material_usage = normalize_material_usage(material_usage)
        selected_smart_cut_rule_reasons = (
            _normalize_selected_smart_cut_rule_reasons(smart_cut_rule_reasons)
            if smart_cut_rule_reasons is not None
            else None
        )
        normalized_material_enhancement_modes = _normalize_material_enhancement_modes(material_enhancement_modes)
        normalized_hyperframes_options = _normalize_hyperframes_options_payload(hyperframes_options)
        normalized_start_mode = _normalize_create_start_mode(start_mode)
        selected_agent_capability_keys = (
            _normalize_agent_capability_keys(agent_capability_keys)
            if agent_capability_keys is not None
            else None
        )
        selected_agent_capability_keys = _merge_hyperframes_capability_keys(
            selected_agent_capability_keys,
            normalized_hyperframes_options,
        )
        selected_smart_cut_rule_reasons = _smart_cut_rule_reasons_from_capabilities(
            selected_smart_cut_rule_reasons,
            selected_agent_capability_keys,
        )
        selected_agent_capability_keys = _merge_smart_cut_capability_key(
            selected_agent_capability_keys,
            selected_smart_cut_rule_reasons,
        )
        workflow_template = workflow_template_for_edit_mode(edit_mode) or workflow_template
        enhancement_modes = _merge_hyperframes_enhancement_modes(
            normalize_enhancement_modes(
                enhancement_modes if enhancement_modes is not None else settings.default_job_enhancement_modes,
            ),
            normalized_hyperframes_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    resolved_creator_card: CreatorCard | None = None
    if parsed_creator_card_id is not None:
        resolved_creator_card = await session.get(CreatorCard, parsed_creator_card_id)
        if resolved_creator_card is None:
            raise HTTPException(status_code=422, detail="creator_card_id does not exist")
    else:
        default_packaging_creator = await _infer_single_complete_packaging_creator_card(session)
        if default_packaging_creator is not None:
            parsed_creator_card_id = default_packaging_creator.id
            resolved_creator_card = default_packaging_creator

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        local_source_files = [
            await _save_uploaded_file(upload, target_dir=temp_root, index=index, settings=settings)
            for index, upload in enumerate(uploaded_files)
        ]

        if len(local_source_files) == 1:
            source_path = local_source_files[0]
            source_name = Path(uploaded_files[0].filename or source_path.name).name
        else:
            source_name = _build_merged_source_name(uploaded_files)
            source_path = await _merge_upload_files_for_job(local_source_files, output_path=temp_root / source_name)

        source_context = _build_job_source_context(
            uploaded_files=uploaded_files,
            source_name=source_name,
            video_description=task_brief or video_description,
            product_controls={
                "edit_mode": edit_mode,
                "automation_level": automation_level,
                "material_usage": material_usage,
            },
            smart_cut_rules=(
                _smart_cut_rules_payload_from_selected_reasons(selected_smart_cut_rule_reasons)
                if selected_smart_cut_rule_reasons is not None
                else None
            ),
            material_enhancement_modes=normalized_material_enhancement_modes,
            hyperframes_options=normalized_hyperframes_options,
            translation_target_language=translation_target_language,
            capability_overrides=(
                _capability_overrides_from_selected_keys(selected_agent_capability_keys)
                if selected_agent_capability_keys is not None
                else None
            ),
        )

        job_id = uuid.uuid4()
        storage = get_storage()
        storage.ensure_bucket()
        s3_key = job_key(str(job_id), source_name)
        storage.upload_file(source_path, s3_key)

        job = Job(
            id=job_id,
            source_path=s3_key,
            source_name=source_name,
            status="awaiting_init" if normalized_start_mode == "manual" else "pending",
            language=language,
            workflow_template=workflow_template,
            job_flow_mode=job_flow_mode,
            workflow_mode=workflow_mode,
            enhancement_modes=enhancement_modes,
            output_dir=output_dir,
            creator_card_id=parsed_creator_card_id,
            task_brief=task_brief,
            execution_mode=execution_mode,
            platform_targets_json=normalized_platform_targets,
        )
        if resolved_creator_card is not None:
            job.creator_card = resolved_creator_card
        session.add(job)

        steps = create_job_steps(job_id)
        step_initial_status = "awaiting_init" if normalized_start_mode == "manual" else "pending"
        for step in steps:
            step.status = step_initial_status
            if step.step_name == "content_profile" and source_context:
                step.metadata_ = {
                    **(step.metadata_ or {}),
                    "source_context": source_context,
                }
            session.add(step)

        await _ensure_job_agent_plan(session, job)

        await session.commit()
        await session.refresh(job)

        result = await session.execute(
            select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
        )
        job = result.scalar_one()
        _attach_job_preview(job)

    return job


def _normalize_video_description(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:4000]


JOB_AGENT_PLAN_REVISION_ARTIFACT_TYPE = "job_agent_plan_revision"


async def _resolve_job_agent_plan_dependencies(
    session: AsyncSession,
    job: Job,
) -> tuple[CreatorCard | None, CreatorTaskStrategy | None, CreatorVisualPlan | None, CreatorPublicationProfile | None]:
    creator = await session.get(CreatorCard, job.creator_card_id) if job.creator_card_id else None
    task_strategy: CreatorTaskStrategy | None = None
    visual_plan: CreatorVisualPlan | None = None
    publication_profile: CreatorPublicationProfile | None = None
    if creator is not None:
        task_strategy_result = await session.execute(
            select(CreatorTaskStrategy)
            .where(
                CreatorTaskStrategy.creator_card_id == creator.id,
                CreatorTaskStrategy.is_active.is_(True),
            )
            .order_by(CreatorTaskStrategy.updated_at.desc())
        )
        task_strategy = task_strategy_result.scalars().first()
        visual_plan_result = await session.execute(
            select(CreatorVisualPlan)
            .where(
                CreatorVisualPlan.creator_card_id == creator.id,
                CreatorVisualPlan.is_active.is_(True),
            )
            .order_by(CreatorVisualPlan.updated_at.desc())
        )
        visual_plan = visual_plan_result.scalars().first()
        publication_result = await session.execute(
            select(CreatorPublicationProfile)
            .where(CreatorPublicationProfile.creator_card_id == creator.id)
            .order_by(CreatorPublicationProfile.updated_at.desc())
        )
        publication_profile = publication_result.scalars().first()
    return creator, task_strategy, visual_plan, publication_profile


def _build_job_agent_plan_payload(
    job: Job,
    *,
    creator: CreatorCard | None,
    task_strategy: CreatorTaskStrategy | None,
    visual_plan: CreatorVisualPlan | None,
    publication_profile: CreatorPublicationProfile | None,
) -> dict[str, Any]:
    task_brief_text = str(job.task_brief or getattr(job, "video_description", "") or "").strip()
    creator_name = str(getattr(creator, "name", "") or "").strip()
    strategy_payload = dict(getattr(task_strategy, "strategy_payload_json", {}) or {})
    visual_payload = dict(getattr(visual_plan, "visual_payload_json", {}) or {})
    publication_payload = dict(getattr(publication_profile, "publication_payload_json", {}) or {})
    execution_mode = str(job.execution_mode or "auto").strip() or "auto"
    stage_rows = [
        {
            "key": "material_understanding",
            "label": "素材理解",
            "summary": "读取素材、文件名和任务想法，确认这条内容的主体与主线。",
        },
        {
            "key": "task_strategy",
            "label": "任务策略",
            "summary": strategy_payload.get("intent") or "根据创作者定位选择默认剪辑策略。",
        },
        {
            "key": "visual_plan",
            "label": "视觉包装",
            "summary": visual_payload.get("cover_direction") or "根据创作者定位生成视觉与文案方案。",
        },
        {
            "key": "publication_plan",
            "label": "发布物料",
            "summary": publication_payload.get("publication_mode") or "根据创作者默认平台准备发布物料。",
        },
    ]
    return {
        "creator": {
            "id": str(creator.id) if creator is not None else None,
            "name": creator_name or None,
            "positioning": str(getattr(creator, "positioning", "") or getattr(creator, "natural_language_profile", "") or "").strip() or None,
        },
        "task_brief": task_brief_text,
        "execution_mode": execution_mode,
        "platform_targets": list(job.platform_targets_json or []),
        "task_strategy": {
            "id": str(task_strategy.id) if task_strategy is not None else None,
            "name": str(getattr(task_strategy, "name", "") or "").strip() or "兼容默认策略",
            "summary": str(getattr(task_strategy, "summary", "") or strategy_payload.get("intent") or "未绑定创作者策略，沿用兼容默认策略。").strip(),
            "payload": strategy_payload,
        },
        "visual_plan": {
            "id": str(visual_plan.id) if visual_plan is not None else None,
            "name": str(getattr(visual_plan, "name", "") or "").strip() or "兼容默认视觉",
            "summary": str(getattr(visual_plan, "summary", "") or visual_payload.get("agent_reason") or "未绑定创作者视觉方案，沿用兼容默认视觉。").strip(),
            "payload": visual_payload,
        },
        "publication_plan": {
            "id": str(publication_profile.id) if publication_profile is not None else None,
            "summary": str(publication_payload.get("agent_reason") or "未绑定创作者发布管理，沿用兼容发布配置。").strip(),
            "payload": publication_payload,
        },
        "stages": stage_rows,
        "why": [
            f"创作者：{creator_name}" if creator_name else "未绑定创作者，当前任务使用兼容默认路径。",
            f"执行方式：{execution_mode}",
            f"任务想法：{task_brief_text or '未填写'}",
        ],
    }


async def _record_job_agent_plan_revision(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    plan_payload: dict[str, Any],
    prompt: str | None,
    operation: str,
) -> None:
    session.add(
        Artifact(
            job_id=job_id,
            artifact_type=JOB_AGENT_PLAN_REVISION_ARTIFACT_TYPE,
            data_json={
                "operation": operation,
                "prompt": prompt,
                "plan_payload": plan_payload,
            },
        )
    )


async def _ensure_job_agent_plan(
    session: AsyncSession,
    job: Job,
    *,
    regenerate: bool = False,
) -> JobAgentPlan:
    result = await session.execute(select(JobAgentPlan).where(JobAgentPlan.job_id == job.id))
    plan = result.scalar_one_or_none()
    creator, task_strategy, visual_plan, publication_profile = await _resolve_job_agent_plan_dependencies(session, job)
    payload = _build_job_agent_plan_payload(
        job,
        creator=creator,
        task_strategy=task_strategy,
        visual_plan=visual_plan,
        publication_profile=publication_profile,
    )
    if plan is None:
        plan = JobAgentPlan(
            job_id=job.id,
            creator_card_id=creator.id if creator is not None else None,
            task_strategy_id=task_strategy.id if task_strategy is not None else None,
            visual_plan_id=visual_plan.id if visual_plan is not None else None,
            publication_profile_id=publication_profile.id if publication_profile is not None else None,
            status="ready",
            plan_payload_json=payload,
        )
        try:
            async with session.begin_nested():
                session.add(plan)
                await session.flush()
                await _record_job_agent_plan_revision(
                    session,
                    job_id=job.id,
                    plan_payload=payload,
                    prompt=str(job.task_brief or getattr(job, "video_description", "") or "").strip() or None,
                    operation="generate",
                )
        except IntegrityError:
            result = await session.execute(select(JobAgentPlan).where(JobAgentPlan.job_id == job.id))
            existing_plan = result.scalar_one_or_none()
            if existing_plan is None:
                raise
            return existing_plan
        return plan
    if regenerate:
        plan.creator_card_id = creator.id if creator is not None else None
        plan.task_strategy_id = task_strategy.id if task_strategy is not None else None
        plan.visual_plan_id = visual_plan.id if visual_plan is not None else None
        plan.publication_profile_id = publication_profile.id if publication_profile is not None else None
        plan.plan_payload_json = payload
        plan.status = "ready"
        await _record_job_agent_plan_revision(
            session,
            job_id=job.id,
            plan_payload=payload,
            prompt="regenerate",
            operation="regenerate",
        )
    return plan


def _normalize_uploaded_sources(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> list[UploadFile]:
    normalized = [item for item in (files or []) if item is not None]
    if normalized:
        return normalized
    if file is not None:
        return [file]
    return []


def _concat_list_entry(path: Path) -> str:
    normalized = str(path).replace("\\", "/")
    escaped = normalized.replace("'", "\\'")
    return f"file '{escaped}'"


async def _run_concat_ffmpeg(
    list_file: Path,
    output_path: Path,
    *,
    transcode: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-movflags",
        "+faststart",
    ]
    if transcode:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    else:
        cmd.extend(["-c", "copy"])
    cmd.append(str(output_path))

    settings = get_settings()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )


async def _merge_upload_files_for_job(file_paths: list[Path], *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        list_file = Path(tmpdir) / "files.txt"
        with list_file.open("w", encoding="utf-8") as handle:
            for path in file_paths:
                handle.write(_concat_list_entry(path))
                handle.write("\n")

        result = await _run_concat_ffmpeg(list_file, output_path, transcode=False)
        if result.returncode != 0:
            if output_path.exists():
                output_path.unlink()
            result = await _run_concat_ffmpeg(list_file, output_path, transcode=True)

    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg concat merge failed: {result.stderr[-500:]}")
    return output_path


def _build_merged_source_name(uploaded_files: list[UploadFile]) -> str:
    first_name = str(uploaded_files[0].filename or "").strip() if uploaded_files else ""
    first_stem = Path(first_name or "video").stem or "video"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", first_stem).strip("._-") or "video"
    return f"merged_{len(uploaded_files)}_{safe_stem[:48]}.mp4"


def _build_job_source_context(
    *,
    uploaded_files: list[UploadFile] | None = None,
    source_name: str | None = None,
    video_description: str | None,
    merged_source_names: list[str] | None = None,
    allow_related_profiles: bool = False,
    product_controls: dict[str, Any] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    material_enhancement_modes: list[str] | None = None,
    hyperframes_options: dict[str, bool] | None = None,
    translation_target_language: str | None = None,
    capability_overrides: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source_context: dict[str, Any] = {}
    if video_description:
        source_context["video_description"] = video_description
    if isinstance(product_controls, dict) and product_controls:
        source_context["product_controls"] = {
            "edit_mode": normalize_edit_mode(product_controls.get("edit_mode")),
            "automation_level": normalize_automation_level(product_controls.get("automation_level")),
            "material_usage": normalize_material_usage(product_controls.get("material_usage")),
        }
    if isinstance(smart_cut_rules, dict) and smart_cut_rules:
        normalized_smart_cut_rules = normalize_smart_cut_rules_payload(smart_cut_rules)
        enabled_reasons = [
            reason
            for reason in _normalize_selected_smart_cut_rule_reasons(
                json.dumps(list(smart_cut_rules.get("enabled_reasons") or []), ensure_ascii=False)
            )
        ]
        if enabled_reasons:
            normalized_smart_cut_rules["enabled_reasons"] = enabled_reasons
        source_context["smart_cut_rules"] = normalized_smart_cut_rules
    normalized_material_enhancement_modes = [
        str(item).strip()
        for item in list(material_enhancement_modes or [])
        if str(item).strip() in _MATERIAL_ENHANCEMENT_MODES
    ]
    if normalized_material_enhancement_modes:
        source_context["material_enhancement_modes"] = list(dict.fromkeys(normalized_material_enhancement_modes))
    if translation_target_language is not None:
        translation_target = _normalize_translation_target_language(translation_target_language)
        source_context["translation"] = (
            {"target_language_mode": "auto"}
            if translation_target == "auto"
            else {"target_language_mode": "manual", "target_language": translation_target}
        )
    source_context["hyperframes_options"] = normalize_hyperframes_options(hyperframes_options)
    normalized_capability_overrides = {
        key: "disabled"
        for key, state in dict(capability_overrides or {}).items()
        if key in CAPABILITY_KEYS and str(state or "").strip().lower() == "disabled"
    }
    if normalized_capability_overrides:
        source_context["capability_overrides"] = normalized_capability_overrides
    resolved_merged_source_names = [
        str(item).strip()
        for item in (merged_source_names or [])
        if str(item).strip()
    ]
    if uploaded_files and len(uploaded_files) > 1 and not resolved_merged_source_names:
        resolved_merged_source_names = [
            str(item.filename or "").strip()
            for item in uploaded_files
            if str(item.filename or "").strip()
        ]
    if resolved_merged_source_names:
        source_context["allow_related_profiles"] = bool(allow_related_profiles or len(resolved_merged_source_names) > 1)
    return enrich_source_context_with_filename_hints(
        source_context,
        source_name=source_name,
        merged_source_names=resolved_merged_source_names,
    )


async def _save_uploaded_file(
    upload: UploadFile,
    *,
    target_dir: Path,
    index: int,
    settings,
) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File extension {suffix!r} not allowed. Allowed: {settings.allowed_extensions}",
        )

    original_name = Path(upload.filename or f"video_{index + 1}{suffix}").name
    target_path = target_dir / f"{index:02d}_{original_name}"
    total_size = 0

    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if settings.max_upload_size_bytes > 0 and total_size > settings.max_upload_size_bytes:
                    raise HTTPException(status_code=413, detail="File too large")
                handle.write(chunk)
    finally:
        await upload.close()

    return target_path


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job)
        .options(
            selectinload(Job.steps),
            selectinload(Job.artifacts),
            selectinload(Job.publication_attempts),
            selectinload(Job.creator_card),
        )
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _attach_job_preview(job)
    return job


@router.get("/{job_id}/agent-plan", response_model=JobAgentPlanOut)
async def get_job_agent_plan(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    plan = await _ensure_job_agent_plan(session, job)
    await session.commit()
    await session.refresh(plan)
    return plan


@router.post("/{job_id}/agent-plan/refine", response_model=JobAgentPlanOut)
async def refine_job_agent_plan(
    job_id: uuid.UUID,
    body: JobAgentPlanRefineIn,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    plan = await _ensure_job_agent_plan(session, job)
    payload = dict(plan.plan_payload_json or {})
    target = str(body.target or "general").strip() or "general"
    adjustments = dict(payload.get("adjustments") or {})
    target_adjustments = list(adjustments.get(target) or [])
    target_adjustments.append(body.prompt.strip())
    adjustments[target] = target_adjustments
    payload["adjustments"] = adjustments
    payload["why"] = [*list(payload.get("why") or []), f"调整 {target}：{body.prompt.strip()}"]
    if target == "visual":
        visual_plan = dict(payload.get("visual_plan") or {})
        visual_plan["summary"] = f"{visual_plan.get('summary') or ''} 调整：{body.prompt.strip()}".strip()
        payload["visual_plan"] = visual_plan
    elif target == "publication":
        publication_plan = dict(payload.get("publication_plan") or {})
        publication_plan["summary"] = f"{publication_plan.get('summary') or ''} 调整：{body.prompt.strip()}".strip()
        payload["publication_plan"] = publication_plan
    else:
        strategy_plan = dict(payload.get("task_strategy") or {})
        strategy_plan["summary"] = f"{strategy_plan.get('summary') or ''} 调整：{body.prompt.strip()}".strip()
        payload["task_strategy"] = strategy_plan
    plan.plan_payload_json = payload
    plan.status = "refined"
    await _record_job_agent_plan_revision(
        session,
        job_id=job.id,
        plan_payload=payload,
        prompt=body.prompt.strip(),
        operation=f"refine:{target}",
    )
    await session.commit()
    await session.refresh(plan)
    return plan


@router.post("/{job_id}/agent-plan/apply", response_model=JobAgentPlanOut)
async def apply_job_agent_plan(
    job_id: uuid.UUID,
    body: JobAgentPlanApplyIn | None = None,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    plan = await _ensure_job_agent_plan(session, job)
    payload = dict(plan.plan_payload_json or {})
    if body and body.selected_strategy_id is not None:
        plan.task_strategy_id = body.selected_strategy_id
    if body and body.selected_visual_plan_id is not None:
        plan.visual_plan_id = body.selected_visual_plan_id
    if body and body.selected_publication_profile_id is not None:
        plan.publication_profile_id = body.selected_publication_profile_id
    payload["applied_at"] = datetime.now(timezone.utc).isoformat()
    plan.plan_payload_json = payload
    plan.status = "applied"
    await _record_job_agent_plan_revision(
        session,
        job_id=job.id,
        plan_payload=payload,
        prompt=None,
        operation="apply",
    )
    await session.commit()
    await session.refresh(plan)
    return plan


@router.get("/{job_id}/agent-decisions", response_model=list[JobAgentDecisionOut])
async def get_job_agent_decisions(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    plan = await _ensure_job_agent_plan(session, job)
    await session.commit()
    payload = dict(plan.plan_payload_json or {})
    items = [
        JobAgentDecisionOut(
            kind="creator",
            title="创作者卡片",
            summary=str(((payload.get("creator") or {}).get("name")) or "未绑定创作者"),
            detail=((payload.get("creator") or {}).get("positioning")),
            status=plan.status,
            version=1,
        ),
        JobAgentDecisionOut(
            kind="task_strategy",
            title="任务策略",
            summary=str(((payload.get("task_strategy") or {}).get("name")) or "兼容默认策略"),
            detail=((payload.get("task_strategy") or {}).get("summary")),
            status=plan.status,
            version=1,
        ),
        JobAgentDecisionOut(
            kind="visual_plan",
            title="智能视觉方案",
            summary=str(((payload.get("visual_plan") or {}).get("name")) or "兼容默认视觉"),
            detail=((payload.get("visual_plan") or {}).get("summary")),
            status=plan.status,
            version=1,
        ),
        JobAgentDecisionOut(
            kind="publication_plan",
            title="智能发布管理",
            summary=str(((payload.get("publication_plan") or {}).get("summary")) or "兼容默认发布配置"),
            detail=f"平台目标：{' / '.join(list(payload.get('platform_targets') or [])) or '跟随创作者默认平台'}",
            status=plan.status,
            version=1,
        ),
    ]
    return items


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"done", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")

    _revoke_running_steps(job.steps or [])

    now = datetime.now(timezone.utc)
    job.status = "cancelled"
    job.error_message = "Cancelled by user"
    job.updated_at = now
    for step in job.steps or []:
        metadata = dict(step.metadata_ or {})
        last_task_id = str(metadata.pop("task_id", "") or "").strip()
        metadata.pop("queue", None)
        metadata.pop("retry_wait_until", None)
        metadata.pop("retry_after_sec", None)
        if last_task_id:
            metadata["last_task_id"] = last_task_id
        metadata["updated_at"] = now.isoformat()
        if step.status == "pending":
            step.status = "skipped"
            step.finished_at = now
            step.metadata_ = {
                **metadata,
                "detail": "任务已取消，后续流程停止。",
            }
        elif step.status == "running":
            step.status = "cancelled"
            step.error_message = "Cancelled by user"
            step.finished_at = now
            step.metadata_ = {
                **metadata,
                "detail": "任务已取消，后续流程停止。",
            }
    render_outputs_result = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_id))
    render_outputs = render_outputs_result.scalars().all()
    await session.commit()
    cleanup_job_runtime_files(
        str(job_id),
        artifacts=list(job.artifacts or []),
        render_outputs=render_outputs,
        purge_deliverables=True,
        preserve_storage_keys=[str(job.source_path or "").strip()],
    )
    await session.refresh(job)
    _attach_job_preview(job)
    return job


@router.post("/{job_id}/restart", response_model=JobOut)
async def restart_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"done", "cancelled", "failed", "awaiting_manual_edit", "needs_review", "processing", "running"}:
        raise HTTPException(
            status_code=409,
            detail="Only completed, running, review-paused, manual-edit-paused, cancelled, or failed jobs can be restarted",
        )

    is_remix_production = _job_is_remix_production(job)
    preserved_source_context = _extract_job_source_context_from_steps(job.steps or [])
    _revoke_running_steps(job.steps or [])
    await _clear_job_runtime_state(job_id, session, source_path=str(job.source_path or "").strip())

    now = datetime.now(timezone.utc)
    job.status = "pending"
    job.error_message = None
    job.updated_at = now
    if is_remix_production:
        remix_step_names = {"content_profile", REMIX_PRODUCTION_STEP_NAME}
        for step in list(job.steps or []):
            if step.step_name not in remix_step_names:
                await session.delete(step)
                (job.steps or []).remove(step)

        steps = list(job.steps or [])
        content_step = _find_step(steps, "content_profile")
        if content_step is None:
            content_step = JobStep(job_id=job.id, step_name="content_profile", status="done")
            session.add(content_step)
            (job.steps or []).append(content_step)
        remix_step = _find_step(steps, REMIX_PRODUCTION_STEP_NAME)
        if remix_step is None:
            remix_step = JobStep(job_id=job.id, step_name=REMIX_PRODUCTION_STEP_NAME, status="pending")
            session.add(remix_step)
            (job.steps or []).append(remix_step)

        content_step.status = "done"
        content_step.attempt = 0
        content_step.started_at = None
        content_step.finished_at = now
        content_step.error_message = None
        content_step.metadata_ = {
            "source_context": preserved_source_context,
            "detail": "二创生产任务元数据已保留，等待重新启动。",
            "updated_at": now.isoformat(),
        } if preserved_source_context else {
            "detail": "二创生产任务已重新开始，但缺少源任务元数据，请重新导入 manifest。",
            "updated_at": now.isoformat(),
        }

        remix_step.status = "pending"
        remix_step.attempt = 0
        remix_step.started_at = None
        remix_step.finished_at = None
        remix_step.error_message = None
        remix_step.metadata_ = {
            "source_context": preserved_source_context,
            "detail": "任务已重新开始，等待启动解说二创生产。",
            "progress": 0.0,
            "updated_at": now.isoformat(),
        } if preserved_source_context else {
            "detail": "任务已重新开始，等待 manifest 元数据恢复。",
            "progress": 0.0,
            "updated_at": now.isoformat(),
        }
    else:
        job.file_hash = None
        existing_step_names = {step.step_name for step in job.steps or []}
        for step_name in PIPELINE_STEPS:
            if step_name in existing_step_names:
                continue
            step = JobStep(job_id=job.id, step_name=step_name, status="pending")
            session.add(step)
            (job.steps or []).append(step)

        ordered_steps = _ordered_steps(job.steps or [])
        for step in ordered_steps:
            step.status = "pending"
            step.attempt = 0
            step.started_at = None
            step.finished_at = None
            step.error_message = None
            step.metadata_ = None
        if ordered_steps:
            ordered_steps[0].metadata_ = {
                "detail": "任务已重新开始，等待调度器派发。",
                "updated_at": now.isoformat(),
            }

    await session.commit()
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one()
    _attach_job_preview(job)
    return job


@router.post("/{job_id}/rerun", response_model=JobRerunActionOut)
async def rerun_job_from_quality_action(
    job_id: uuid.UUID,
    request: JobRerunActionIn | None = None,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    steps = _ordered_steps(list(job.steps or []))
    if not steps:
        raise HTTPException(status_code=409, detail="Job steps are missing")

    plan: JobRerunPlan = resolve_job_rerun_request(
        request=JobRerunRequest(
            issue_code=request.issue_code if request else None,
            rerun_start_step=request.rerun_start_step if request else None,
            note=request.note if request else None,
        ),
        artifacts=list(job.artifacts or []),
    )
    if not plan.rerun_steps:
        raise HTTPException(status_code=409, detail="No rerun steps resolved for this request")

    await execute_job_rerun_plan(
        session,
        job=job,
        steps=steps,
        plan=plan,
        via="web",
    )
    await session.commit()

    return JobRerunActionOut(
        job_id=str(job.id),
        job_status=str(job.status),
        rerun_start_step=plan.rerun_start_step,
        rerun_steps=list(plan.rerun_steps),
        issue_codes=list(plan.issue_codes),
        note=plan.note,
        detail=build_job_rerun_detail(plan),
    )


@router.post("/{job_id}/initialize", response_model=JobOut)
async def initialize_job(
    job_id: uuid.UUID,
    body: JobInitializeIn,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "awaiting_init":
        raise HTTPException(status_code=409, detail="Only awaiting-init jobs can be initialized")

    now = datetime.now(timezone.utc)
    existing_source_context = _extract_job_source_context_from_steps(job.steps or [])
    updated_source_context = _build_job_source_context(
        source_name=job.source_name,
        video_description=body.video_description,
        merged_source_names=[
            str(item).strip()
            for item in (existing_source_context.get("merged_source_names") or [])
            if str(item).strip()
        ],
        allow_related_profiles=bool(existing_source_context.get("allow_related_profiles")),
        product_controls=body.model_dump(include={"edit_mode", "automation_level", "material_usage"}, exclude_none=True)
        or existing_source_context.get("product_controls"),
    )
    source_context = {
        **existing_source_context,
        **(updated_source_context or {}),
    }
    resolved_workflow_template = workflow_template_for_edit_mode(body.edit_mode) or body.workflow_template

    job.status = "pending"
    job.error_message = None
    job.updated_at = now
    job.language = body.language
    job.workflow_template = resolved_workflow_template
    job.job_flow_mode = body.job_flow_mode
    job.workflow_mode = body.workflow_mode
    job.enhancement_modes = body.enhancement_modes
    job.output_dir = body.output_dir

    existing_step_names = {step.step_name for step in job.steps or []}
    for step_name in PIPELINE_STEPS:
        if step_name in existing_step_names:
            continue
        step = JobStep(job_id=job.id, step_name=step_name, status="pending")
        session.add(step)
        (job.steps or []).append(step)

    ordered_steps = _ordered_steps(job.steps or [])
    for step in ordered_steps:
        preserved_source_context = source_context if step.step_name == "content_profile" and source_context else None
        step.status = "pending"
        step.attempt = 0
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        step.metadata_ = {"source_context": preserved_source_context} if preserved_source_context else None
    if ordered_steps:
        ordered_steps[0].metadata_ = {
            **(ordered_steps[0].metadata_ or {}),
            "detail": "任务已初始化，等待调度器派发。",
            "updated_at": now.isoformat(),
        }

    await session.commit()
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one()
    _attach_job_preview(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    include_family: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    jobs_to_delete = [job]
    if include_family:
        jobs_to_delete = await _resolve_job_delete_family(job, session)

    for target_job in jobs_to_delete:
        _revoke_running_steps(target_job.steps or [])
        await _clear_job_runtime_state(target_job.id, session, source_path="")

    target_ids = [target_job.id for target_job in jobs_to_delete]
    await session.execute(delete(JobStep).where(JobStep.job_id.in_(target_ids)))
    await session.execute(delete(Job).where(Job.id.in_(target_ids)))
    await session.commit()


async def _resolve_job_delete_family(job: Job, session: AsyncSession) -> list[Job]:
    _attach_job_preview(job)
    family_key = _job_queue_family_key(job)
    identity = family_key[0]
    if not identity:
        return [job]

    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.artifacts))
        .where(
            (func.lower(Job.file_hash) == identity)
            | (func.lower(Job.source_path) == identity)
            | (func.lower(Job.source_name) == identity)
        )
    )
    candidates = list(result.scalars().all())
    if not any(candidate.id == job.id for candidate in candidates):
        candidates.append(job)
    _attach_job_previews(candidates, lightweight=True)
    family_jobs = [candidate for candidate in candidates if _job_queue_family_key(candidate) == family_key]
    return family_jobs or [job]


@router.get("/{job_id}/report", response_model=ReportOut)
async def get_report(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = await generate_report(job_id, session)
    return report


@router.get("/{job_id}/timeline")
async def get_timeline(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Timeline).where(Timeline.job_id == job_id, Timeline.timeline_type == "editorial")
    )
    timeline = result.scalar_one_or_none()
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return {"id": str(timeline.id), "version": timeline.version, "data": timeline.data_json}


def _manual_editor_detail_for_job_status(status_value: str) -> str | None:
    normalized = str(status_value or "").strip().lower()
    if normalized == "awaiting_init":
        return "当前任务尚未完成初始化，请先填写必要任务信息。"
    return None


def _manual_editor_prerequisite_detail(steps: list[JobStep] | None) -> str | None:
    step_map = {step.step_name: step for step in (steps or [])}
    edit_plan_step = step_map.get("edit_plan")
    if edit_plan_step is not None and edit_plan_step.status == "done":
        return None
    for step_name in PIPELINE_STEPS:
        if step_name in MANUAL_EDITOR_OPTIONAL_PREREQUISITE_STEPS:
            continue
        step = step_map.get(step_name)
        if step_name == "edit_plan":
            if step is None or step.status != "done":
                return "手动调整需要等到剪辑时间线和渲染计划生成完成。"
            return None
        if step is None:
            return "手动调整需要等到上游分析步骤生成完成。"
        if step.status not in {"done", "skipped"}:
            return f"手动调整需要等到上游步骤 {STEP_LABELS.get(step_name, step_name)} 完成。"
    return "手动调整需要等到剪辑时间线和渲染计划生成完成。"


def _manual_editor_apply_conflict_detail(steps: list[JobStep] | None) -> str | None:
    prerequisite_detail = _manual_editor_prerequisite_detail(steps)
    if prerequisite_detail:
        return prerequisite_detail
    running_downstream_steps = [
        step.step_name
        for step in (steps or [])
        if step.step_name == "render" and step.status == "running"
    ]
    if running_downstream_steps:
        labels = "、".join(STEP_LABELS.get(step_name, step_name) for step_name in running_downstream_steps)
        return f"当前 {labels} 正在运行。可以先预览和调整，但请等待该步骤结束后再保存，避免并发覆盖输出。"
    return None


def _manual_editor_segment_payload(segment: dict[str, Any], *, index: int) -> ManualEditorSegmentOut:
    start = max(0.0, float(segment.get("start", 0.0) or 0.0))
    end = max(start, float(segment.get("end", start) or start))
    return ManualEditorSegmentOut(
        start=round(start, 3),
        end=round(end, 3),
        duration_sec=round(max(0.0, end - start), 3),
        source_index=index,
    )


def _manual_editor_silence_payload(segment: dict[str, Any], *, source: str = "audio_vad") -> ManualEditorSilenceOut | None:
    try:
        start = max(0.0, float(segment.get("start", 0.0) or 0.0))
        end = max(start, float(segment.get("end", start) or start))
    except (TypeError, ValueError):
        return None
    if end <= start + 0.08:
        return None
    return ManualEditorSilenceOut(
        start=round(start, 3),
        end=round(end, 3),
        duration_sec=round(end - start, 3),
        source=str(segment.get("source") or source or "audio_vad"),
    )


def _manual_editor_smart_cut_rules_payload(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return default_smart_cut_rules_payload()
    normalized = normalize_smart_cut_rules_payload(payload)
    return normalized or default_smart_cut_rules_payload()


def _manual_editor_smart_delete_source(item: dict[str, Any]) -> tuple[str, float | None]:
    if str(item.get("candidate_stage") or "").strip() in {"manual_editor_full_transcript", "manual_editor_smart_cut_rules"}:
        try:
            return "manual_editor_rule_candidate", round(float(item.get("score", 0.0) or 0.0), 3)
        except (TypeError, ValueError):
            return "manual_editor_rule_candidate", None
    multimodal_review = item.get("multimodal_review") if isinstance(item.get("multimodal_review"), dict) else {}
    if str(multimodal_review.get("verdict") or "").strip().lower() == "cut":
        try:
            return "multimodal_trim_review", round(float(multimodal_review.get("confidence", 0.0) or 0.0), 3)
        except (TypeError, ValueError):
            return "multimodal_trim_review", None
    llm_review = item.get("llm_review") if isinstance(item.get("llm_review"), dict) else {}
    if str(llm_review.get("verdict") or "").strip().lower() == "cut":
        try:
            return "llm_cut_review", round(float(llm_review.get("confidence", 0.0) or 0.0), 3)
        except (TypeError, ValueError):
            return "llm_cut_review", None
    return "auto_edit_decision", None


def _manual_editor_rule_segment_payload(item: dict[str, Any]) -> ManualEditorRuleSegmentOut | None:
    reason = str(item.get("reason") or "").strip()
    kind = rule_kind(reason)
    if not kind:
        return None
    stage = str(item.get("candidate_stage") or "accepted_cut").strip() or "accepted_cut"
    rule_id = str(item.get("rule_id") or item.get("candidate_id") or "").strip() or None
    if not rule_id:
        raw_rule_id = item.get("id")
        rule_id = str(raw_rule_id or "").strip() or None
    match_surface = str(item.get("match_surface") or "").strip()
    match_surface_layer = str(item.get("match_surface_layer") or "").strip()
    try:
        start = max(0.0, float(item.get("start", 0.0) or 0.0))
        end = max(start, float(item.get("end", start) or start))
    except (TypeError, ValueError):
        return None
    if end <= start + 0.02:
        return None
    source, confidence = _manual_editor_smart_delete_source(item)
    llm_review = item.get("llm_review") if isinstance(item.get("llm_review"), dict) else {}
    multimodal_review = item.get("multimodal_review") if isinstance(item.get("multimodal_review"), dict) else {}
    evidence_payload = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    evidence: list[str] = []
    for text in list(multimodal_review.get("evidence") or []):
        cleaned = str(text).strip()
        if cleaned:
            evidence.append(cleaned)
    for text in list(llm_review.get("evidence") or []):
        cleaned = str(text).strip()
        if cleaned:
            evidence.append(cleaned)
    for key in ("previous_text", "next_text"):
        cleaned = str(evidence_payload.get(key) or "").strip()
        if cleaned:
            evidence.append(cleaned)
    if not match_surface:
        if reason == "filler_word" and str(item.get("filler_mode") or "").strip():
            match_surface = str(item.get("filler_mode") or "").strip()
        else:
            match_surface = str(item.get("source_text") or "").strip() or None
    if not match_surface_layer:
        match_surface_layer = rule_match_surface_layer(reason) or ""
    detail = (
        str(multimodal_review.get("reason") or "").strip()
        or str(llm_review.get("reason") or "").strip()
        or rule_label(reason)
    )
    auto_applied = bool(item.get("auto_applied"))
    if str(item.get("candidate_stage") or "").strip() in {"manual_editor_full_transcript", "manual_editor_smart_cut_rules"}:
        auto_applied = False
    return ManualEditorRuleSegmentOut(
        start=round(start, 3),
        end=round(end, 3),
        duration_sec=round(end - start, 3),
        kind=kind,
        reason=reason,
        stage=stage,
        rule_id=rule_id,
        match_surface=match_surface,
        risk_level=str(item.get("risk_level") or "").strip() or None,
        source=source,
        confidence=confidence,
        match_surface_layer=match_surface_layer or None,
        detail=detail or None,
        evidence=list(dict.fromkeys(evidence))[:4],
        auto_applied=auto_applied,
        filler_mode=str(item.get("filler_mode") or "").strip() or None,
        source_text=str(item.get("source_text") or "").strip() or None,
    )


def _manual_editor_rule_segments(editorial_analysis: dict[str, Any] | None) -> list[ManualEditorRuleSegmentOut]:
    accepted_cuts, rule_candidates = cut_analysis_candidate_items(editorial_analysis, resolved=True)
    segments = [
        normalized
        for item in [*accepted_cuts, *rule_candidates]
        if (normalized := _manual_editor_rule_segment_payload(item)) is not None
    ]
    deduped: list[ManualEditorRuleSegmentOut] = []
    seen: set[tuple[str, float, float, str]] = set()
    for segment in sorted(
        segments,
        key=lambda item: (item.start, item.end, item.kind, item.reason),
    ):
        key = (segment.kind, segment.start, segment.end, segment.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(segment)
    return deduped


def _manual_editor_cut_analysis_payload(
    artifact_payload: dict[str, Any] | None,
    editorial_analysis: dict[str, Any] | None,
    *,
    source_name: str,
    job_flow_mode: str,
    source_subtitles: list[dict[str, Any]] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(artifact_payload, dict) and str(artifact_payload.get("schema") or "").strip() == CUT_ANALYSIS_SCHEMA_VERSION:
        rule_candidates_payload = artifact_payload.get("rule_candidates")
        if not isinstance(rule_candidates_payload, list):
            rule_candidates_payload = []
        if not rule_candidates_payload:
            rule_candidates_payload = artifact_payload.get("manual_editor_rule_candidates")
            if not isinstance(rule_candidates_payload, list):
                rule_candidates_payload = []
        rule_candidates = [
            dict(item)
            for item in list(
                rule_candidates_payload or []
            )
            if isinstance(item, dict)
        ]
        resolved_editorial_analysis = artifact_payload if editorial_analysis is not None else {
            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
            "accepted_cuts": list(artifact_payload.get("accepted_cuts") or []),
            "rule_candidates": rule_candidates,
            "silence_segments": list(artifact_payload.get("silence_segments") or []),
            "source_timeline_contract": dict(artifact_payload.get("source_timeline_contract") or {}),
            "automatic_gate": dict(artifact_payload.get("automatic_gate") or {}),
            "review_focus": artifact_payload.get("review_focus", ""),
        }
        return build_cut_analysis_payload(
            editorial_analysis=resolved_editorial_analysis,
            source_name=source_name,
            job_flow_mode=job_flow_mode,
            source_subtitles=source_subtitles,
            smart_cut_rules=smart_cut_rules,
            content_profile=content_profile,
        )
    return build_cut_analysis_payload(
        editorial_analysis=editorial_analysis,
        source_name=source_name,
        job_flow_mode=job_flow_mode,
        source_subtitles=source_subtitles,
        smart_cut_rules=smart_cut_rules,
        content_profile=content_profile,
    )


async def _load_manual_editor_cut_analysis_payload(
    session: AsyncSession,
    *,
    job: Job,
    editorial_timeline_payload: dict[str, Any] | None,
    editorial_analysis: dict[str, Any] | None = None,
    source_subtitles: list[dict[str, Any]] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_cut_analysis_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=(ARTIFACT_TYPE_CUT_ANALYSIS,),
    )
    resolved_editorial_analysis = (
        copy.deepcopy(editorial_analysis)
        if isinstance(editorial_analysis, dict)
        else editorial_timeline_analysis(editorial_timeline_payload) or None
    )
    return _manual_editor_cut_analysis_payload(
        current_cut_analysis_artifact.data_json
        if current_cut_analysis_artifact and isinstance(current_cut_analysis_artifact.data_json, dict)
        else None,
        resolved_editorial_analysis,
        source_name=str(job.source_name or ""),
        job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
        source_subtitles=source_subtitles,
        smart_cut_rules=smart_cut_rules,
        content_profile=content_profile,
    )


def _manual_editor_refine_decision_plan_payload(
    artifact_payload: dict[str, Any] | None,
    *,
    keep_segments: list[dict[str, Any]],
    source_duration_sec: float,
    subtitle_fingerprint: str | None,
    render_plan_version: int | None,
    cut_analysis: dict[str, Any] | None,
    audio_defaults: dict[str, Any] | None,
    video_transform: dict[str, Any] | None,
    smart_cut_rules: dict[str, Any] | None,
    mode: str,
    note: str | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
) -> dict[str, Any]:
    if isinstance(artifact_payload, dict) and str(artifact_payload.get("schema") or "").strip() == REFINE_DECISION_PLAN_SCHEMA_VERSION:
        return normalize_refine_decision_plan_strategy_metadata(
            artifact_payload,
            cut_analysis=cut_analysis,
        )
    return build_refine_decision_plan_payload(
        keep_segments=keep_segments,
        source_duration_sec=source_duration_sec,
        mode=mode,
        subtitle_fingerprint=subtitle_fingerprint,
        render_plan_version=render_plan_version,
        cut_analysis=cut_analysis,
        audio_defaults=audio_defaults,
        video_transform=video_transform,
        smart_cut_rules=smart_cut_rules,
        note=note,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
    )


def _manual_editor_build_refine_decision_plan_from_render_plan(
    *,
    keep_segments: list[dict[str, Any]],
    source_duration_sec: float,
    subtitle_fingerprint: str | None,
    render_plan_data: dict[str, Any] | None,
    render_plan_version: int | None,
    cut_analysis: dict[str, Any] | None,
    audio_defaults: dict[str, Any] | None = None,
    video_transform: dict[str, Any] | None,
    smart_cut_rules: dict[str, Any] | None,
    mode: str,
    note: str | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
) -> dict[str, Any]:
    resolved_render_plan_data = (
        None
        if isinstance(audio_defaults, dict)
        else (render_plan_data if isinstance(render_plan_data, dict) else None)
    )
    return build_refine_decision_plan_from_render_plan(
        keep_segments=keep_segments,
        source_duration_sec=source_duration_sec,
        mode=mode,
        subtitle_fingerprint=subtitle_fingerprint,
        render_plan_data=resolved_render_plan_data,
        render_plan_version=render_plan_version,
        cut_analysis=cut_analysis,
        audio_defaults=audio_defaults,
        video_transform=video_transform,
        smart_cut_rules=smart_cut_rules,
        note=note,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
    )


def _manual_editor_editorial_context(
    editorial_timeline_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = editorial_timeline_payload if isinstance(editorial_timeline_payload, dict) else {}
    return {
        "subtitle_projection": editorial_timeline_subtitle_projection(payload),
        "editorial_analysis": editorial_timeline_analysis(payload) or None,
        "raw_keep_segments": _manual_keep_segments_from_editorial_payload(payload),
    }


def _manual_editor_packaging_plan_from_render_plan(
    render_plan: dict[str, Any] | None = None,
    *,
    render_plan_context: dict[str, Any] | None = None,
    packaging_timeline: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_packaging_timeline = dict(packaging_timeline) if isinstance(packaging_timeline, dict) else None
    resolved_delivery = dict(delivery) if isinstance(delivery, dict) else None
    if (
        resolved_packaging_timeline is None
        or resolved_delivery is None
    ):
        resolved_render_plan_context = (
            render_plan_context if isinstance(render_plan_context, dict) else _manual_editor_render_plan_context(render_plan)
        )
        if resolved_packaging_timeline is None:
            resolved_packaging_timeline = dict(resolved_render_plan_context.get("packaging_timeline") or {})
        if resolved_delivery is None:
            resolved_delivery = dict(resolved_render_plan_context.get("delivery") or {})
    subtitles = dict((resolved_packaging_timeline or {}).get("subtitles") or {})
    editing_accents = dict((resolved_packaging_timeline or {}).get("editing_accents") or {})
    intro_plan = packaging_timeline_asset_plan(resolved_packaging_timeline, "intro")
    outro_plan = packaging_timeline_asset_plan(resolved_packaging_timeline, "outro")
    insert_plan = packaging_timeline_insert_plan(resolved_packaging_timeline)
    watermark_plan = packaging_timeline_asset_plan(resolved_packaging_timeline, "watermark")
    music_plan = packaging_timeline_asset_plan(resolved_packaging_timeline, "music")
    return {
        "subtitle_style": str(subtitles.get("style") or "bold_yellow_outline"),
        "subtitle_motion_style": str(subtitles.get("motion_style") or "motion_static"),
        "smart_effect_style": str(editing_accents.get("style") or "smart_effect_commercial"),
        "intro": intro_plan,
        "outro": outro_plan,
        "insert": insert_plan,
        "watermark": watermark_plan,
        "music": music_plan,
        "export_resolution_mode": str((resolved_delivery or {}).get("resolution_mode") or "source"),
        "export_resolution_preset": str((resolved_delivery or {}).get("resolution_preset") or "1080p"),
        "export_frame_rate_mode": str((resolved_delivery or {}).get("frame_rate_mode") or "source"),
        "export_frame_rate_preset": str((resolved_delivery or {}).get("frame_rate_preset") or "30"),
    }


def _manual_editor_render_plan_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(render_plan or {}) if isinstance(render_plan, dict) else {}
    return {
        "packaging_timeline": resolve_packaging_timeline_payload(payload),
        "workflow_preset": render_plan_workflow_preset(payload),
        "delivery": render_plan_delivery(payload),
        "video_transform": render_plan_video_transform(payload),
        "loudness": render_plan_loudness(payload),
        "voice_processing": render_plan_voice_processing(payload),
        "dialogue_polish_plan": render_plan_dialogue_polish(payload),
        "avatar_commentary_plan": render_plan_avatar_commentary(payload),
        "strategy_review_context": render_plan_strategy_review_context(payload),
    }


async def _load_packaging_creator_card_for_job(session: AsyncSession, job: Job) -> CreatorCard | None:
    if job.creator_card_id:
        result = await session.execute(
            select(CreatorCard)
            .options(selectinload(CreatorCard.assets))
            .where(CreatorCard.id == job.creator_card_id)
        )
        creator = result.scalar_one_or_none()
        if creator is not None:
            return creator
    return await _infer_single_complete_packaging_creator_card(session)


async def _infer_single_complete_packaging_creator_card(session: AsyncSession) -> CreatorCard | None:
    result = await session.execute(
        select(CreatorCard)
        .options(selectinload(CreatorCard.assets))
        .where(CreatorCard.status == "active")
        .order_by(CreatorCard.updated_at.desc(), CreatorCard.created_at.desc())
    )
    candidates = [
        creator
        for creator in result.scalars().all()
        if creator_has_complete_packaging_assets(list(getattr(creator, "assets", []) or []))
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _manual_editor_multimodal_trim_review_payload(
    *,
    cut_analysis_payload: dict[str, Any] | None,
    source_name: str,
    job_flow_mode: str,
) -> dict[str, Any]:
    return build_multimodal_trim_review_payload(
        cut_analysis_payload,
        source_name=source_name,
        job_flow_mode=job_flow_mode,
    )


def _manual_editor_multimodal_review_source_meta(
    *,
    job: Job,
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = dict(content_profile or {}) if isinstance(content_profile, dict) else {}
    return {
        "job_id": str(job.id),
        "source_name": str(job.source_name or "").strip(),
        "job_flow_mode": str(getattr(job, "job_flow_mode", "") or "auto"),
        "subject_brand": str(profile.get("subject_brand") or "").strip(),
        "subject_model": str(profile.get("subject_model") or "").strip(),
        "subject_type": str(profile.get("subject_type") or "").strip(),
    }


async def _load_manual_editor_multimodal_trim_review_payload(
    session: AsyncSession,
    *,
    job: Job,
    cut_analysis_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    current_multimodal_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=(ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,),
    )
    current_payload = (
        current_multimodal_artifact.data_json
        if current_multimodal_artifact and isinstance(current_multimodal_artifact.data_json, dict)
        else None
    )
    if multimodal_trim_review_matches_cut_analysis(
        current_payload,
        cut_analysis_payload,
        source_name=str(job.source_name or ""),
        job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
    ):
        return dict(current_payload or {})
    return _manual_editor_multimodal_trim_review_payload(
        cut_analysis_payload=cut_analysis_payload,
        source_name=str(job.source_name or ""),
        job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
    )


def _manual_editor_final_subtitle_text(item: dict[str, Any]) -> str:
    return _manual_editor_source_editable_text(subtitle_display_rule_text(item))


def _manual_editor_editable_final_subtitle_text(item: dict[str, Any]) -> str:
    if str(item.get("display_suppressed_reason") or "").strip() == "standalone_filler":
        return _manual_editor_source_editable_text(
            item.get("text_final")
            or item.get("text_norm")
            or item.get("text_raw", "")
        )
    return _manual_editor_source_editable_text(subtitle_display_rule_text(item))


def _manual_editor_editable_text(value: Any) -> str:
    return normalize_source_transcript_text(value)


def _manual_editor_source_editable_text(value: Any) -> str:
    return normalize_source_transcript_text(value, collapse_stutter=False)


def _manual_editor_raw_editable_text(value: Any) -> str:
    return normalize_source_transcript_text(value)


def _manual_editor_display_source_text(item: dict[str, Any], *, final_text: str = "") -> str:
    return _manual_editor_source_editable_text(
        subtitle_display_rule_text(item)
        or final_text
    )


def _manual_editor_timing_text(item: dict[str, Any], *, final_text: str = "") -> str:
    return _manual_editor_source_editable_text(
        item.get("timing_text")
        or subtitle_display_rule_text(item)
        or final_text
    )


def _manual_editor_lcs_index_pairs(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    if not left or not right:
        return []
    rows = len(left) + 1
    cols = len(right) + 1
    table = [[0] * cols for _ in range(rows)]
    for row in range(1, rows):
        for col in range(1, cols):
            table[row][col] = (
                table[row - 1][col - 1] + 1
                if left[row - 1] == right[col - 1]
                else max(table[row - 1][col], table[row][col - 1])
            )
    pairs: list[tuple[int, int]] = []
    row = len(left)
    col = len(right)
    while row > 0 and col > 0:
        if left[row - 1] == right[col - 1]:
            pairs.append((row - 1, col - 1))
            row -= 1
            col -= 1
        elif table[row - 1][col] >= table[row][col - 1]:
            row -= 1
        else:
            col -= 1
    pairs.reverse()
    return pairs


def _manual_editor_normalize_alignment_token_payloads(
    tokens: list[dict[str, Any]],
    *,
    canonical_text: str,
) -> list[dict[str, Any]]:
    canonical_units = subtitle_display_units(canonical_text)
    if not canonical_units or not tokens:
        return tokens

    raw_units: list[dict[str, Any]] = []
    for token in tokens:
        text = str((token or {}).get("text") or "")
        units = subtitle_display_units(text)
        if not units:
            continue
        try:
            start = float((token or {}).get("start", 0.0) or 0.0)
            end = float((token or {}).get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        for offset, unit in enumerate(units):
            raw_units.append(
                {
                    "text": unit,
                    "key": subtitle_display_unit_key(unit),
                    "start": round(start + duration * (offset / len(units)), 3),
                    "end": round(start + duration * ((offset + 1) / len(units)), 3),
                }
            )
    if not raw_units:
        return tokens

    pairs = _manual_editor_lcs_index_pairs(
        [subtitle_display_unit_key(unit) for unit in canonical_units],
        [str(unit["key"]) for unit in raw_units],
    )
    matched_by_canonical = {canonical_index: raw_index for canonical_index, raw_index in pairs}
    if has_unsafe_unmatched_alnum_units(
        canonical_units,
        matched_indexes=set(matched_by_canonical),
    ):
        return tokens
    normalized: list[dict[str, Any]] = []
    previous_end = raw_units[0]["start"]
    for canonical_index, unit in enumerate(canonical_units):
        raw_index = matched_by_canonical.get(canonical_index)
        raw_unit = raw_units[raw_index] if raw_index is not None else None
        start = float(raw_unit["start"]) if raw_unit else float(previous_end)
        end = float(raw_unit["end"]) if raw_unit else max(start + 0.001, float(previous_end))
        previous_end = max(float(previous_end), end)
        normalized.append(
            {
                "text": unit,
                "start": round(start, 3),
                "end": round(end, 3),
                "source": "span_alignment",
            }
        )
    return normalized


def _clean_manual_editor_subtitle_projection(
    subtitles: list[dict[str, Any]],
    *,
    drop_empty: bool = True,
    collapse_repeats: bool = True,
    clean_text: bool = True,
) -> list[dict[str, Any]]:
    return clean_subtitle_payloads(
        subtitles,
        drop_empty=drop_empty,
        collapse_repeats=collapse_repeats,
        clean_text=clean_text,
    )


def _manual_editor_has_collapsed_repeat_runs(
    raw_subtitles: list[dict[str, Any]],
    cleaned_subtitles: list[dict[str, Any]],
) -> bool:
    return len(raw_subtitles) > len(cleaned_subtitles)


def _manual_editor_should_use_clean_fallback_projection(
    raw_subtitles: list[dict[str, Any]],
    cleaned_subtitles: list[dict[str, Any]],
    projection_data: dict[str, Any] | None,
) -> bool:
    return _manual_editor_has_collapsed_repeat_runs(raw_subtitles, cleaned_subtitles)


def _manual_editor_projection_data_uses_canonical(projection_data: dict[str, Any] | None) -> bool:
    projection_kind = str((projection_data or {}).get("projection_kind") or "").strip()
    transcript_layer = str((projection_data or {}).get("transcript_layer") or "").strip()
    return projection_kind == "display_baseline" and transcript_layer == "canonical_transcript"


def _manual_editor_projection_data_is_current(projection_data: dict[str, Any] | None) -> bool:
    return subtitle_projection_data_is_current(projection_data)


def _manual_editor_projection_entries_use_canonical(entries: list[dict[str, Any]]) -> bool:
    return any(str(item.get("projection_source") or "") == "canonical_transcript" for item in entries)


def _manual_editor_canonical_layer_namespace(canonical_layer: dict[str, Any] | None) -> SimpleNamespace:
    raw_segments = list((canonical_layer or {}).get("segments") or [])
    segments: list[SimpleNamespace] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            continue
        surfaces = subtitle_surface_item_dict(
            segment,
            generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
        )
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
        segments.append(
            SimpleNamespace(
                index=int(segment.get("index", index) or index),
                start=float(segment.get("start", 0.0) or 0.0),
                end=float(segment.get("end", 0.0) or 0.0),
                text_norm=surfaces["text_norm"],
                text_canonical=surfaces["text_norm"],
                text_raw=surfaces["text_raw"] or surfaces["text_norm"],
                text_final=surfaces["text_final"],
                display_suppressed_reason=str(segment.get("display_suppressed_reason") or "").strip() or None,
                words=tuple(words),
            )
        )
    return SimpleNamespace(
        segments=tuple(segments),
        source_basis=str((canonical_layer or {}).get("source_basis") or "canonical_transcript"),
        correction_metrics=dict((canonical_layer or {}).get("correction_metrics") or {}),
        alignment_engine_version=str((canonical_layer or {}).get("alignment_engine_version") or ""),
    )


async def _manual_editor_rebuild_projection_entries_from_canonical_layer(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    canonical_layer: dict[str, Any] | None,
    projection_data: dict[str, Any] | None,
    fallback_items: list[SubtitleItem] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical_namespace = _manual_editor_canonical_layer_namespace(canonical_layer)
    if not list(getattr(canonical_namespace, "segments", ()) or ()):
        return [], {}
    subtitle_items = list(fallback_items or await _load_manual_editor_subtitle_items(session, job_id=job_id))
    job = await session.get(Job, job_id)
    source_name = str(getattr(job, "source_name", "") or "")
    from roughcut.pipeline.steps import _build_canonical_refresh_projection

    refreshed_projection_layer, _, _ = await _build_canonical_refresh_projection(
        session,
        job_id=job_id,
        source_name=source_name,
        subtitle_items=subtitle_items,
        canonical_transcript_layer=canonical_namespace,
        projection_data=dict(projection_data or {}),
    )
    projection_entries = [
        _manual_editor_subtitle_projection_entry_payload(entry.as_dict())
        for entry in list(getattr(refreshed_projection_layer, "entries", ()) or ())
    ]
    refreshed_projection_data = (
        refreshed_projection_layer.as_dict()
        if hasattr(refreshed_projection_layer, "as_dict")
        else dict(projection_data or {})
    )
    return projection_entries, refreshed_projection_data


def _manual_editor_drop_redundant_synthetic_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return drop_redundant_synthetic_word_payloads(words)


def _manual_editor_word_payload(item: dict[str, Any], *, prefer_raw_text: bool = False) -> ManualEditorWordOut | None:
    try:
        start = max(0.0, float(item.get("start", 0.0) or 0.0))
        end = max(start, float(item.get("end", start) or start))
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    word = (
        str(item.get("raw_text") or item.get("word") or item.get("text") or "").strip()
        if prefer_raw_text
        else str(item.get("word") or item.get("raw_text") or item.get("text") or "").strip()
    )
    if not word:
        return None
    confidence = item.get("confidence")
    try:
        normalized_confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        normalized_confidence = None
    alignment = item.get("alignment")
    source = None
    if isinstance(alignment, dict):
        roughcut_alignment = alignment.get("_roughcut")
        if isinstance(roughcut_alignment, dict):
            source = str(roughcut_alignment.get("source") or "") or None
        source = source or str(alignment.get("source") or "") or None
    source = source or str(item.get("source") or item.get("provider") or "") or None
    return ManualEditorWordOut(
        word=word,
        start=round(start, 3),
        end=round(end, 3),
        confidence=normalized_confidence,
        source=source,
    )


async def _load_manual_editor_word_payloads(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    prefer_raw_text: bool = False,
    normalize_to_text: bool = True,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id)
        .order_by(TranscriptSegment.version.desc(), TranscriptSegment.segment_index.asc())
    )
    rows = result.scalars().all()
    if not rows:
        return []
    sanitize_transcript_segment_word_rows(rows)
    latest_version = max(int(row.version or 1) for row in rows)
    words: list[dict[str, Any]] = []
    for row in rows:
        if int(row.version or 1) != latest_version:
            continue
        row_words: list[dict[str, Any]] = []
        for word in _manual_editor_drop_redundant_synthetic_words(list(row.words_json or [])):
            if not isinstance(word, dict):
                continue
            payload = _manual_editor_word_payload(word, prefer_raw_text=prefer_raw_text)
            if payload is None:
                continue
            row_words.append(payload.model_dump())
        words.extend(
            _manual_editor_normalize_word_payloads_for_text(row_words, row.text)
            if normalize_to_text
            else row_words
        )
    words.sort(key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)))
    return words


def _manual_editor_normalize_word_payloads_for_text(words: list[dict[str, Any]], text: Any) -> list[dict[str, Any]]:
    canonical_text = normalize_editable_subtitle_text(text) or normalize_editable_subtitle_text(
        "".join(str(word.get("word") or "") for word in words)
    )
    canonical_units = subtitle_display_units(canonical_text)
    if not canonical_units or not words:
        return words

    raw_units: list[dict[str, Any]] = []
    for word in words:
        units = subtitle_display_units(str(word.get("word") or ""))
        if not units:
            continue
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        for offset, unit in enumerate(units):
            raw_units.append(
                {
                    "text": unit,
                    "key": subtitle_display_unit_key(unit),
                    "start": round(start + duration * (offset / len(units)), 3),
                    "end": round(start + duration * ((offset + 1) / len(units)), 3),
                    "word": word,
                }
            )
    if not raw_units:
        return words

    pairs = _manual_editor_lcs_index_pairs(
        [subtitle_display_unit_key(unit) for unit in canonical_units],
        [str(unit["key"]) for unit in raw_units],
    )
    matched_by_canonical = {canonical_index: raw_index for canonical_index, raw_index in pairs}
    if has_unsafe_unmatched_alnum_units(
        canonical_units,
        matched_indexes=set(matched_by_canonical),
    ):
        return words
    normalized: list[dict[str, Any]] = []
    previous_end = float(raw_units[0]["start"])
    for canonical_index, unit in enumerate(canonical_units):
        raw_index = matched_by_canonical.get(canonical_index)
        raw_unit = raw_units[raw_index] if raw_index is not None else None
        raw_word = dict(raw_unit.get("word") or {}) if raw_unit else {}
        start = float(raw_unit["start"]) if raw_unit else previous_end
        end = float(raw_unit["end"]) if raw_unit else max(start + 0.001, previous_end)
        previous_end = max(previous_end, end)
        normalized.append(
            {
                **raw_word,
                "word": unit,
                "start": round(start, 3),
                "end": round(end, 3),
                "source": raw_word.get("source") or "transcript_words",
            }
        )
    sanitized = drop_redundant_synthetic_word_payloads(normalized)
    if len(sanitized) != len(normalized):
        return []
    if _manual_editor_word_payloads_have_collapsed_timing(sanitized):
        return []
    return sanitized


def _manual_editor_word_payloads_have_collapsed_timing(words: list[dict[str, Any]]) -> bool:
    return word_payloads_have_collapsed_timing(words)


def _attach_manual_editor_words_to_subtitles(
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not words:
        return subtitles
    if any(
        str(item.get("projection_source") or "") in {"canonical_transcript", "transcript_segment"}
        for item in subtitles
        if isinstance(item, dict)
    ):
        return subtitles
    if not subtitles:
        return _manual_editor_orphan_word_subtitles(subtitles, words)
    annotated: list[dict[str, Any]] = []
    covered_word_ids: set[int] = set()
    subtitle_ranges = _manual_editor_subtitle_ranges(subtitles)
    word_owner_indexes = {
        id(word): owner_index
        for word in words
        if (owner_index := _manual_editor_best_subtitle_range_index(word, subtitle_ranges)) is not None
    }
    for subtitle_order_index, item in enumerate(subtitles):
        payload = dict(item)
        try:
            start_time = float(payload.get("start_time", payload.get("start", 0.0)) or 0.0)
            float(payload.get("end_time", payload.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            annotated.append(payload)
            continue
        overlapping_words: list[dict[str, Any]] = []
        for word in words:
            if id(word) in covered_word_ids:
                continue
            if word_owner_indexes.get(id(word)) != subtitle_order_index:
                continue
            overlapping_words.append(word)
        attached_words, represented_word_ids = _manual_editor_represented_words_for_subtitle(payload, overlapping_words)
        if overlapping_words:
            payload["words"] = overlapping_words
            covered_word_ids.update(id(word) for word in overlapping_words)
        else:
            payload["words"] = attached_words
            covered_word_ids.update(represented_word_ids)
        annotated.append(payload)
    annotated.extend(_manual_editor_orphan_word_subtitles(annotated, [word for word in words if id(word) not in covered_word_ids]))
    annotated.sort(key=lambda item: (float(item.get("start_time", item.get("start", 0.0)) or 0.0), float(item.get("end_time", item.get("end", 0.0)) or 0.0)))
    return annotated


def _manual_editor_subtitle_ranges(subtitles: list[dict[str, Any]]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for index, item in enumerate(subtitles):
        try:
            start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            end = float(item.get("end_time", item.get("end", start)) or start)
        except (TypeError, ValueError):
            start = end = 0.0
        ranges.append((start, end))
    return ranges


def _manual_editor_best_subtitle_range_index(
    word: dict[str, Any],
    ranges: list[tuple[float, float]],
) -> int | None:
    try:
        word_start = float(word.get("start", 0.0) or 0.0)
        word_end = float(word.get("end", word_start) or word_start)
    except (TypeError, ValueError):
        return None
    if word_end <= word_start:
        return None
    center = (word_start + word_end) / 2.0
    best_index: int | None = None
    best_score: tuple[float, int, float] = (0.0, 0, float("-inf"))
    duration = max(word_end - word_start, 0.001)
    for index, (start, end) in enumerate(ranges):
        if end <= start:
            continue
        overlap = min(word_end, end) - max(word_start, start)
        if overlap <= 0.001:
            continue
        center_inside = 1 if start <= center < end else 0
        score = (overlap / duration, center_inside, start)
        if score > best_score:
            best_index = index
            best_score = score
    return best_index


def _manual_editor_word_belongs_to_range(word: dict[str, Any], *, start: float, end: float) -> bool:
    try:
        word_start = float(word.get("start", 0.0) or 0.0)
        word_end = float(word.get("end", word_start) or word_start)
    except (TypeError, ValueError):
        return False
    if word_end <= word_start or end <= start:
        return False
    overlap = min(word_end, end) - max(word_start, start)
    if overlap <= 0.001:
        return False
    duration = max(word_end - word_start, 0.001)
    center = (word_start + word_end) / 2.0
    return overlap / duration >= 0.5 or start <= center < end


def _manual_editor_projection_item_has_row_word_timing_mismatch(
    item: dict[str, Any],
    *,
    tolerance_sec: float = 0.35,
) -> bool:
    words = [
        word
        for word in drop_redundant_synthetic_word_payloads(list(item.get("words") or item.get("words_json") or []))
        if isinstance(word, dict)
    ]
    if not words:
        return False
    try:
        row_start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
        row_end = float(item.get("end_time", item.get("end", row_start)) or row_start)
    except (TypeError, ValueError):
        return False
    if row_end <= row_start:
        return False
    timed: list[tuple[float, float]] = []
    for word in words:
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        timed.append((start, end))
    if not timed:
        return False
    word_start = min(start for start, _ in timed)
    word_end = max(end for _, end in timed)
    return word_start < row_start - tolerance_sec or word_end > row_end + tolerance_sec


def _manual_editor_sanitize_projection_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    if not _manual_editor_projection_item_has_row_word_timing_mismatch(payload):
        return payload
    payload.pop("words", None)
    payload.pop("words_json", None)
    payload.pop("transcript_text", None)
    return payload


def _manual_editor_represented_words_for_subtitle(
    subtitle: dict[str, Any],
    words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int]]:
    canonical_text = _manual_editor_display_source_text(
        subtitle,
        final_text=_manual_editor_final_subtitle_text(subtitle),
    )
    canonical_units = subtitle_display_units(canonical_text)
    if not canonical_units or not words:
        return [], set()

    raw_units: list[dict[str, Any]] = []
    for word in words:
        units = subtitle_display_units(str(word.get("word") or word.get("raw_text") or word.get("text") or ""))
        if not units:
            continue
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        for offset, unit in enumerate(units):
            raw_units.append(
                {
                    "key": subtitle_display_unit_key(unit),
                    "start": start + duration * (offset / len(units)),
                    "end": start + duration * ((offset + 1) / len(units)),
                    "word": word,
                }
            )
    if not raw_units:
        return [], set()

    pairs = _manual_editor_lcs_index_pairs(
        [subtitle_display_unit_key(unit) for unit in canonical_units],
        [str(unit["key"]) for unit in raw_units],
    )
    represented_word_ids = {
        id(raw_units[raw_index]["word"])
        for _, raw_index in pairs
        if 0 <= raw_index < len(raw_units)
    }
    represented_words = [word for word in words if id(word) in represented_word_ids]
    return represented_words, represented_word_ids


def _manual_editor_orphan_word_subtitles(
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose transcript words that landed in subtitle gaps so manual cuts are visible."""
    if not words:
        return []

    orphan_words: list[dict[str, Any]] = []
    for word in words:
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        text = str(word.get("word") or word.get("raw_text") or word.get("text") or "").strip()
        if not text:
            continue
        orphan_words.append({**word, "start": start, "end": end, "word": text})
    if not orphan_words:
        return []

    groups: list[list[dict[str, Any]]] = []
    for word in sorted(orphan_words, key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0))):
        previous_group = groups[-1] if groups else []
        previous_word = previous_group[-1] if previous_group else None
        current_text = "".join(str(item.get("word") or "") for item in previous_group)
        gap = float(word.get("start", 0.0) or 0.0) - float((previous_word or {}).get("end", 0.0) or 0.0)
        if (
            not previous_group
            or gap > 0.55
            or len(current_text) >= 18
            or float(word.get("end", 0.0) or 0.0) - float(previous_group[0].get("start", 0.0) or 0.0) > 5.0
        ):
            groups.append([word])
            continue
        previous_group.append(word)

    next_index = max((int(item.get("index", -1) or -1) for item in subtitles), default=-1) + 1
    virtual_rows: list[dict[str, Any]] = []
    for group in groups:
        text = "".join(str(item.get("word") or "") for item in group).strip()
        if not text:
            continue
        start = float(group[0].get("start", 0.0) or 0.0)
        end = float(group[-1].get("end", start) or start)
        if end <= start:
            continue
        if _manual_editor_orphan_word_group_is_neighbor_duplicate(text, start=start, end=end, subtitles=subtitles):
            continue
        virtual_rows.append(
            {
                "index": next_index,
                "source_index": next_index,
                "source_indexes": [next_index],
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "text_raw": text,
                "text_norm": text,
                "text_final": text,
                "display_suppressed_reason": None,
                "projection_source": "transcript_segment",
                "words": group,
                "virtual": True,
            }
        )
        next_index += 1
    return virtual_rows


def _manual_editor_absorb_short_boundary_orphan_groups(
    subtitles: list[dict[str, Any]],
    groups: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    if not subtitles or not groups:
        return groups
    remaining: list[list[dict[str, Any]]] = []
    for group in groups:
        text = normalize_editable_subtitle_text("".join(str(item.get("word") or "") for item in group))
        key = _manual_editor_compact_text_key(text)
        if not key or len(key) > 2:
            remaining.append(group)
            continue
        start = float(group[0].get("start", 0.0) or 0.0)
        end = float(group[-1].get("end", start) or start)
        if _manual_editor_orphan_word_group_is_neighbor_duplicate(text, start=start, end=end, subtitles=subtitles):
            continue
        target: dict[str, Any] | None = None
        mode = "suffix"
        best_score: tuple[float, int] = (float("inf"), 9)
        for item in subtitles:
            try:
                item_start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
                item_end = float(item.get("end_time", item.get("end", item_start)) or item_start)
            except (TypeError, ValueError):
                continue
            if item_start - 0.001 <= start and end <= item_end + 0.001 and (0.0, -1) < best_score:
                target = item
                mode = "merge"
                best_score = (0.0, -1)
            before_gap = max(0.0, item_start - end)
            after_gap = max(0.0, start - item_end)
            prefix_score = (before_gap, 0)
            suffix_score = (after_gap, 1)
            if end <= item_start + 0.001 and before_gap <= 0.18 and prefix_score < best_score:
                target = item
                mode = "prefix"
                best_score = prefix_score
            if start >= item_end - 0.001 and after_gap <= 0.18 and suffix_score < best_score:
                target = item
                mode = "suffix"
                best_score = suffix_score
        if target is None:
            remaining.append(group)
            continue
        current_text = _manual_editor_display_source_text(target, final_text=_manual_editor_final_subtitle_text(target))
        existing_words = list(target.get("words") or [])
        if mode == "merge" and existing_words:
            merged_words = sorted(
                [*existing_words, *group],
                key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)),
            )
            merged_text = normalize_editable_subtitle_text("".join(str(item.get("word") or "") for item in merged_words))
        else:
            merged_text = normalize_editable_subtitle_text(f"{text}{current_text}" if mode == "prefix" else f"{current_text}{text}")
        if not merged_text:
            remaining.append(group)
            continue
        target["text_raw"] = merged_text
        target["text_norm"] = merged_text
        target["text_final"] = merged_text
        if mode == "merge" and existing_words:
            target["words"] = sorted(
                [*existing_words, *group],
                key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)),
            )
        else:
            target["words"] = [*group, *existing_words] if mode == "prefix" else [*existing_words, *group]
    return remaining


def _manual_editor_orphan_word_group_is_neighbor_duplicate(
    text: str,
    *,
    start: float,
    end: float,
    subtitles: list[dict[str, Any]],
) -> bool:
    key = _manual_editor_compact_text_key(text)
    if not key:
        return True
    if len(key) > 4:
        return False
    nearby_text = ""
    for index, item in enumerate(subtitles):
        try:
            item_start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            item_end = float(item.get("end_time", item.get("end", item_start)) or item_start)
        except (TypeError, ValueError):
            continue
        if item_end < start - 0.8 or item_start > end + 0.8:
            continue
        nearby_text += _manual_editor_final_subtitle_text(item)
    return key in _manual_editor_compact_text_key(nearby_text)


def _manual_editor_compact_text_key(text: Any) -> str:
    return re.sub(r"[\s，。！？!?；;：:,、（）()\[\]【】{}\"'《》<>]+", "", normalize_editable_subtitle_text(text))


def _manual_editor_text_is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    if not haystack:
        return False
    cursor = 0
    for char in haystack:
        if char == needle[cursor]:
            cursor += 1
            if cursor >= len(needle):
                return True
    return False


def _manual_editor_split_pieces_cover_source_text(
    source_text: Any,
    pieces: list[dict[str, Any]],
) -> bool:
    source_key = _manual_editor_compact_text_key(source_text)
    if not source_key:
        return True
    piece_values = [
        _manual_editor_compact_text_key(str(piece.get("timing_text") or piece.get("text") or ""))
        for piece in pieces
        if isinstance(piece, dict)
    ]
    piece_values = [piece for piece in piece_values if piece]
    if not piece_values:
        return False
    if len(piece_values) == 1:
        return piece_values[0] in source_key or piece_values[0] == source_key
    piece_key = "".join(piece_values)
    if piece_key == source_key:
        return True
    if not piece_key:
        return False
    matches: list[tuple[int, int]] = []
    cursor = 0
    for piece in piece_values:
        start = source_key.find(piece, cursor)
        if start < 0:
            return False
        matches.append((start, start + len(piece)))
        cursor = matches[-1][1]
    if not matches:
        return False
    source_len = len(source_key)
    if source_len <= 0:
        return True
    max_internal_gap = max(6, min(12, int(max(1, source_len * 0.15))))
    for index, (start, end) in enumerate(matches[1:], start=1):
        gap = start - matches[index - 1][1]
        if gap > max_internal_gap:
            return False
    return True


_MANUAL_EDITOR_REVEALABLE_ASR_FILLER_CHARS = frozenset("啊呃额嗯哎唉诶欸吧呀嘛呢哦喔哈")


def _manual_editor_subsequence_extra_text(needle: str, haystack: str) -> str:
    if not needle:
        return haystack
    cursor = 0
    extras: list[str] = []
    for char in haystack:
        if cursor < len(needle) and char == needle[cursor]:
            cursor += 1
        else:
            extras.append(char)
    return "".join(extras) if cursor >= len(needle) else ""


def _manual_editor_should_reveal_asr_source_text(current_text: Any, asr_text: Any) -> bool:
    current_key = _manual_editor_compact_text_key(current_text)
    asr_key = _manual_editor_compact_text_key(asr_text)
    if not asr_key or asr_key == current_key:
        return False
    if not current_key:
        return True
    if not _manual_editor_text_is_subsequence(current_key, asr_key):
        return False
    extra_chars = len(asr_key) - len(current_key)
    if extra_chars <= 0:
        return False
    extra_text = _manual_editor_subsequence_extra_text(current_key, asr_key)
    if not extra_text:
        return False
    filler_extra_count = sum(1 for char in extra_text if char in _MANUAL_EDITOR_REVEALABLE_ASR_FILLER_CHARS)
    if filler_extra_count <= 0:
        return False
    return filler_extra_count / max(1, len(extra_text)) >= 0.6 and (
        extra_chars <= 12 or len(current_key) / max(1, len(asr_key)) >= 0.72
    )


_MANUAL_EDITOR_FLASHLIGHT_CONTEXT_RE = re.compile(
    r"EDC(?:17|23|37)|NITECORE|奈特科尔|手电|电筒|流明|尾按|泛光|聚光",
    re.IGNORECASE,
)
_MANUAL_EDITOR_HOTWORD_CONTEXT_PROFILE_FIELDS = (
    "subject_domain",
    "subject_brand",
    "subject_model",
    "subject_type",
    "content_subject",
    "video_theme",
    "summary",
    "hook_line",
    "visible_text",
)
_MANUAL_EDITOR_GENERIC_HOTWORD_WRONG_FORMS = frozenset(
    {
        "这个",
        "那个",
        "今天",
        "我们",
        "大家",
        "然后",
        "就是",
        "可以",
        "还是",
        "感觉",
    }
)
_MANUAL_EDITOR_ASR_TRANSCRIPT_NOISE_MARKER_RE = re.compile(
    r"(?i)(?:<\|?\s*(?:nospeech|no[_\s-]?speech|silence|music|noise|sounds?|background[_\s-]?noise|environmental[_\s-]?sounds?)\s*\|?>|[♪♫]+)"
)
_MANUAL_EDITOR_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]")


def _manual_editor_apply_source_text_corrections(text: Any, *, context_text: str = "") -> str:
    normalized = normalize_source_transcript_text(text)
    if not normalized:
        return ""
    normalized = normalize_contextual_noc_alias_text(normalized, context_text=context_text)
    normalized = normalize_contextual_unboxing_sale_text(normalized, context_text=context_text)
    if _MANUAL_EDITOR_FLASHLIGHT_CONTEXT_RE.search(f"{context_text}\n{normalized}"):
        normalized = normalize_flashlight_model_alias_text(normalized)
    return normalized


def _manual_editor_normalize_asr_transcript_text(text: Any) -> str:
    normalized = normalize_source_transcript_text(text)
    if not normalized:
        return ""
    normalized = _MANUAL_EDITOR_ASR_TRANSCRIPT_NOISE_MARKER_RE.sub("", normalized)
    return re.sub(r"\s{2,}", " ", normalized).strip()


def _manual_editor_hotword_context_text(job: Job | None, content_profile: dict[str, Any] | None) -> str:
    parts: list[str] = [str(getattr(job, "source_name", "") or "")]
    profile = content_profile if isinstance(content_profile, dict) else {}
    for field in _MANUAL_EDITOR_HOTWORD_CONTEXT_PROFILE_FIELDS:
        value = profile.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for field in ("search_queries", "keywords"):
        values = profile.get(field)
        if isinstance(values, list):
            parts.extend(str(item).strip() for item in values if str(item or "").strip())
    prior = profile.get("transcription_context_prior")
    if isinstance(prior, dict):
        for value in prior.values():
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif isinstance(value, list):
                parts.extend(str(item).strip() for item in value if str(item or "").strip())
    return "\n".join(part for part in parts if part)


def _manual_editor_profile_has_vertical_glossary_evidence(content_profile: dict[str, Any] | None) -> bool:
    if not isinstance(content_profile, dict) or not content_profile:
        return False
    if not str(content_profile.get("subject_domain") or "").strip():
        return False
    for field in ("subject_brand", "subject_model", "subject_type", "content_subject", "video_theme", "summary", "hook_line"):
        value = str(content_profile.get(field) or "").strip()
        if len(value) >= 2:
            return True
    for field in ("search_queries", "keywords"):
        values = content_profile.get(field)
        if isinstance(values, list) and any(len(str(item or "").strip()) >= 2 for item in values):
            return True
    confirmation = content_profile.get("topic_fact_confirmation")
    if isinstance(confirmation, dict) and confirmation.get("subject"):
        return True
    return False


def _manual_editor_normalize_hotword_form(value: Any, *, max_length: int = 80) -> str:
    text = _manual_editor_normalize_asr_transcript_text(value)
    return " ".join(text.split())[:max_length]


def _manual_editor_hotword_replacement_allowed(wrong: str, correct: str) -> bool:
    wrong = _manual_editor_normalize_hotword_form(wrong, max_length=80)
    correct = _manual_editor_normalize_hotword_form(correct, max_length=80)
    if not wrong or not correct or wrong == correct:
        return False
    if wrong.casefold() == correct.casefold():
        return bool(_MANUAL_EDITOR_LATIN_TOKEN_RE.search(correct)) and wrong != correct
    if wrong in _MANUAL_EDITOR_GENERIC_HOTWORD_WRONG_FORMS:
        return False
    if len(wrong) < 2:
        return False
    if model_numbers_conflict(wrong, correct):
        return False
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", wrong + correct))


def _manual_editor_add_hotword_replacement(
    pairs: list[tuple[str, str]],
    seen: set[tuple[str, str]],
    *,
    wrong: Any,
    correct: Any,
) -> None:
    wrong_text = _manual_editor_normalize_hotword_form(wrong, max_length=80)
    correct_text = _manual_editor_normalize_hotword_form(correct, max_length=80)
    if not _manual_editor_hotword_replacement_allowed(wrong_text, correct_text):
        return
    key = (wrong_text.casefold(), correct_text.casefold())
    if key in seen:
        return
    seen.add(key)
    pairs.append((wrong_text, correct_text))


def _manual_editor_hotword_replacements_from_terms(terms: list[dict[str, Any]] | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for term in terms or []:
        if not isinstance(term, dict):
            continue
        correct = term.get("correct_form") or term.get("canonical_form") or term.get("term")
        for wrong in list(term.get("wrong_forms") or []) + list(term.get("aliases") or []):
            _manual_editor_add_hotword_replacement(pairs, seen, wrong=wrong, correct=correct)
        raw_term = term.get("term")
        if raw_term and raw_term != correct:
            _manual_editor_add_hotword_replacement(pairs, seen, wrong=raw_term, correct=correct)
    pairs.sort(key=lambda item: (-len(_manual_editor_compact_text_key(item[0])), -len(item[0]), item[0]))
    return pairs


def _manual_editor_content_profile_hotword_terms(content_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(content_profile, dict):
        return []
    identity_review = content_profile.get("identity_review")
    evidence_bundle = identity_review.get("evidence_bundle") if isinstance(identity_review, dict) else None
    matched_aliases = evidence_bundle.get("matched_glossary_aliases") if isinstance(evidence_bundle, dict) else None
    matched_aliases = matched_aliases if isinstance(matched_aliases, dict) else {}
    field_specs = (
        ("subject_brand", "brand"),
        ("subject_model", "model"),
    )
    terms: list[dict[str, Any]] = []
    for field_name, alias_key in field_specs:
        canonical = _manual_editor_normalize_hotword_form(content_profile.get(field_name), max_length=64)
        if not canonical:
            continue
        aliases: list[str] = []
        for value in matched_aliases.get(alias_key) or []:
            alias = _manual_editor_normalize_hotword_form(value, max_length=64)
            if alias:
                aliases.append(alias)
        for key in (f"{field_name}_aliases", f"{alias_key}_aliases"):
            values = content_profile.get(key)
            if isinstance(values, list):
                aliases.extend(_manual_editor_normalize_hotword_form(value, max_length=64) for value in values)
        aliases = [alias for alias in aliases if alias and alias != canonical]
        if aliases:
            terms.append({"correct_form": canonical, "wrong_forms": aliases, "category": field_name, "source": "content_profile"})
    return terms


async def _load_manual_editor_persisted_glossary_terms(
    session: AsyncSession,
    *,
    domains: list[str],
) -> list[dict[str, Any]]:
    domain_set = {str(domain or "").strip() for domain in domains if str(domain or "").strip()}
    if not domain_set:
        return []
    result = await session.execute(select(GlossaryTerm).where(GlossaryTerm.scope_type.in_(["domain", "global"])))
    terms: list[dict[str, Any]] = []
    for row in result.scalars().all():
        scope_type = str(row.scope_type or "").strip()
        scope_value = str(row.scope_value or "").strip()
        if scope_type == "domain" and scope_value not in domain_set:
            continue
        if scope_type not in {"domain", "global"}:
            continue
        terms.append(
            {
                "correct_form": row.correct_form,
                "wrong_forms": list(row.wrong_forms or []),
                "category": row.category,
                "context_hint": row.context_hint,
                "domain": scope_value if scope_type == "domain" else "",
            }
        )
    return terms


async def _load_manual_editor_transcript_hotword_replacements(
    session: AsyncSession,
    *,
    job: Job,
    content_profile: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    subject_domain = str((content_profile or {}).get("subject_domain") or "").strip()
    learned_hotwords = await load_learned_hotwords(session, subject_domain=subject_domain, limit=80)
    term_payloads: list[dict[str, Any]] = _manual_editor_content_profile_hotword_terms(content_profile)
    term_payloads.extend(
        {
            "term": item.get("term"),
            "canonical_form": item.get("canonical_form") or item.get("term"),
            "aliases": list(item.get("aliases") or []),
        }
        for item in learned_hotwords
        if isinstance(item, dict)
    )
    if _manual_editor_profile_has_vertical_glossary_evidence(content_profile):
        domains = detect_glossary_domains(
            workflow_template=None,
            content_profile=content_profile or {},
            subtitle_items=None,
            source_name=None,
        )
        term_payloads.extend(
            resolve_builtin_glossary_terms(
                workflow_template=None,
                content_profile=content_profile or {},
                subtitle_items=None,
                source_name=None,
            )
        )
        term_payloads.extend(await _load_manual_editor_persisted_glossary_terms(session, domains=domains))
    return _manual_editor_hotword_replacements_from_terms(term_payloads)


def _manual_editor_apply_transcript_hotword_corrections(
    text: Any,
    *,
    context_text: str = "",
    hotword_replacements: list[tuple[str, str]] | None = None,
) -> str:
    normalized = _manual_editor_normalize_asr_transcript_text(text)
    if not normalized:
        return ""
    normalized = normalize_contextual_noc_alias_text(normalized, context_text=context_text)
    if _MANUAL_EDITOR_FLASHLIGHT_CONTEXT_RE.search(f"{context_text}\n{normalized}"):
        normalized = normalize_flashlight_model_alias_text(normalized)
    for wrong, correct in hotword_replacements or []:
        wrong_text = str(wrong or "").strip()
        correct_text = str(correct or "").strip()
        if not wrong_text or not correct_text or wrong_text == correct_text:
            continue
        if _MANUAL_EDITOR_LATIN_TOKEN_RE.search(wrong_text):
            compact_wrong = re.sub(r"\s+", "", wrong_text).casefold()
            compact_normalized = re.sub(r"\s+", "", normalized).casefold()
            if compact_wrong and compact_wrong not in compact_normalized:
                continue
            escaped = re.escape(wrong_text).replace(r"\ ", r"\s*")
            pattern = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
            normalized = pattern.sub(correct_text, normalized)
        else:
            if wrong_text not in normalized:
                continue
            normalized = normalized.replace(wrong_text, correct_text)
    return normalized


def _manual_editor_canonical_segment_source_rows(
    canonical_layer: dict[str, Any],
    *,
    context_text: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fallback_index, segment in enumerate(list(canonical_layer.get("segments") or [])):
        if not isinstance(segment, dict):
            continue
        surfaces = subtitle_surface_item_dict(
            segment,
            generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
        )
        raw_text = str(surfaces["text_raw"] or surfaces["text_norm"] or "").strip()
        canonical_text = str(surfaces["text_norm"] or raw_text)
        final_text = _manual_editor_raw_editable_text(canonical_text)
        raw_display_text = _manual_editor_raw_editable_text(raw_text)
        display_text = raw_display_text if _manual_editor_should_reveal_asr_source_text(final_text, raw_display_text) else final_text
        if not display_text:
            continue
        try:
            index = int(segment.get("index", fallback_index) or fallback_index)
            start_time = max(0.0, float(segment.get("start", segment.get("start_time", 0.0)) or 0.0))
            end_time = max(start_time, float(segment.get("end", segment.get("end_time", start_time)) or start_time))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "index": index,
                "source_index": index,
                "source_indexes": [index],
                "start_time": start_time,
                "end_time": end_time,
                "text_raw": raw_display_text or raw_text or display_text,
                "text_norm": final_text,
                "text_final": display_text,
                "timing_text": display_text,
                "words": [
                    dict(word)
                    for word in list(segment.get("words") or [])
                    if isinstance(word, dict)
                ],
                "display_suppressed_reason": str(segment.get("display_suppressed_reason") or "").strip() or None,
                "projection_source": "canonical_transcript",
            }
        )
    return rows


def _manual_editor_reveal_source_asr_words(
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
    *,
    context_text: str = "",
    hotword_replacements: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not subtitles or not words:
        return subtitles
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(subtitles):
        payload = dict(item)
        segmentation_locked = bool(payload.get("segmentation_locked"))
        try:
            start_time = float(payload.get("start_time", payload.get("start", 0.0)) or 0.0)
            end_time = float(payload.get("end_time", payload.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            rows.append(payload)
            continue
        if end_time <= start_time:
            rows.append(payload)
            continue
        range_words = [
            word
            for word in words
            if _manual_editor_word_belongs_to_range(word, start=start_time, end=end_time)
        ]
        if not range_words:
            rows.append(payload)
            continue
        raw_asr_text = _manual_editor_raw_editable_text(
            "".join(str(word.get("word") or "") for word in range_words),
        )
        asr_text = _manual_editor_apply_transcript_hotword_corrections(
            raw_asr_text,
            context_text=context_text,
            hotword_replacements=hotword_replacements,
        )
        hotword_changed_text = _manual_editor_compact_text_key(asr_text) != _manual_editor_compact_text_key(raw_asr_text)
        final_text = _manual_editor_final_subtitle_text(payload)
        final_key = _manual_editor_compact_text_key(final_text)
        asr_key = _manual_editor_compact_text_key(asr_text)
        if payload.get("words") and final_key and asr_key and not _manual_editor_should_reveal_asr_source_text(final_text, asr_text):
            rows.append(payload)
            continue
        asr_text = _manual_editor_trim_asr_reveal_text_to_source_fragment(
            asr_text,
            payload,
            previous_item=subtitles[index - 1] if index > 0 else None,
            next_item=subtitles[index + 1] if index + 1 < len(subtitles) else None,
        )
        if asr_text:
            payload["transcript_text"] = asr_text
            payload["transcript_text_raw"] = raw_asr_text
            payload["words"] = range_words
            if not hotword_changed_text and not segmentation_locked:
                payload = _manual_editor_tighten_source_row_to_display_words(
                    payload,
                    fallback_text=asr_text,
                    preserve_row_timing=True,
                )
        rows.append(payload)
    return rows


def _manual_editor_align_source_rows_to_asr_words(
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
    *,
    context_text: str = "",
    hotword_replacements: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not subtitles or not words:
        return subtitles
    word_units: list[dict[str, Any]] = []
    normalized_words: list[dict[str, Any]] = []
    for word_index, raw_word in enumerate(words):
        if not isinstance(raw_word, dict):
            continue
        try:
            start = float(raw_word.get("start", 0.0) or 0.0)
            end = float(raw_word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        raw_text = str(raw_word.get("word") or raw_word.get("raw_text") or raw_word.get("text") or "").strip()
        corrected_text = _manual_editor_apply_source_text_corrections(raw_text, context_text=context_text)
        units = subtitle_display_units(corrected_text or raw_text)
        if not units:
            continue
        payload = {**raw_word, "word": raw_text, "start": round(start, 3), "end": round(end, 3)}
        normalized_index = len(normalized_words)
        normalized_words.append(payload)
        duration = end - start
        for unit_index, unit in enumerate(units):
            word_units.append(
                {
                    "key": subtitle_display_unit_key(unit),
                    "start": start + duration * (unit_index / len(units)),
                    "end": start + duration * ((unit_index + 1) / len(units)),
                    "word_index": normalized_index,
                }
            )
    if not word_units:
        return subtitles
    word_unit_starts = [float(unit["start"]) for unit in word_units]
    unit_positions: dict[str, list[int]] = {}
    for index, unit in enumerate(word_units):
        unit_positions.setdefault(str(unit["key"]), []).append(index)

    rows: list[dict[str, Any]] = []
    cursor = 0
    for item in subtitles:
        payload = dict(item)
        segmentation_locked = bool(payload.get("segmentation_locked"))
        anchored_words = [
            dict(word)
            for word in list(payload.get("words") or [])
            if isinstance(word, dict)
        ]
        try:
            original_start = float(payload.get("start_time", payload.get("start", 0.0)) or 0.0)
            original_end = float(payload.get("end_time", payload.get("end", original_start)) or original_start)
        except (TypeError, ValueError):
            original_start = 0.0
            original_end = 0.0
        if anchored_words:
            payload["words"] = anchored_words
            if not segmentation_locked:
                payload = _manual_editor_tighten_source_row_to_display_words(
                    payload,
                    preserve_row_timing=True,
                )
            if original_end > original_start:
                cursor = max(cursor, bisect.bisect_left(word_unit_starts, original_end))
            rows.append(payload)
            continue
        text = _manual_editor_final_subtitle_text(payload)
        target_units = [subtitle_display_unit_key(unit) for unit in subtitle_display_units(text)]
        if not target_units:
            rows.append(payload)
            continue
        original_duration = max(0.0, original_end - original_start)
        window_padding = max(3.0, original_duration * 0.75)
        window_start = max(0.0, original_start - window_padding)
        window_end = original_end + window_padding if original_end > original_start else 0.0
        matched: list[dict[str, Any]] = []
        search_cursor = max(cursor, bisect.bisect_left(word_unit_starts, window_start))
        for key in target_units:
            positions = unit_positions.get(str(key)) or []
            position_index = bisect.bisect_left(positions, search_cursor)
            while position_index < len(positions):
                match_index = positions[position_index]
                candidate = word_units[match_index]
                candidate_center = (float(candidate["start"]) + float(candidate["end"])) / 2.0
                if window_end > window_start and candidate_center > window_end:
                    match_index = -1
                    break
                if window_end <= window_start or candidate_center >= window_start:
                    break
                position_index += 1
            else:
                match_index = -1
            if match_index < 0:
                continue
            matched.append(word_units[match_index])
            search_cursor = match_index + 1
        matched_ratio = len(matched) / max(1, len(target_units))
        if matched_ratio < 0.58 or len(matched) < min(4, len(target_units)):
            rows.append(payload)
            continue
        first_word_index = min(int(unit["word_index"]) for unit in matched)
        last_word_index = max(int(unit["word_index"]) for unit in matched)
        if last_word_index < first_word_index:
            rows.append(payload)
            continue
        matched_start = min(float(unit["start"]) for unit in matched)
        matched_end = max(float(unit["end"]) for unit in matched)
        if matched_end <= matched_start:
            rows.append(payload)
            continue
        if original_end > original_start:
            max_span = max(original_duration * 2.5, original_duration + 6.0)
            if (
                matched_start < window_start
                or matched_end > window_end
                or (matched_end - matched_start) > max_span
            ):
                rows.append(payload)
                cursor = max(cursor, bisect.bisect_left(word_unit_starts, original_end))
                continue
        aligned_words = [dict(word) for word in normalized_words[first_word_index : last_word_index + 1]]
        payload["words"] = aligned_words
        payload["source_overlap_start_time"] = round(matched_start, 3)
        payload["source_overlap_end_time"] = round(matched_end, 3)
        raw_asr_text = _manual_editor_raw_editable_text(
            "".join(str(word.get("word") or "") for word in aligned_words)
        )
        asr_text = _manual_editor_apply_transcript_hotword_corrections(
            raw_asr_text,
            context_text=context_text,
            hotword_replacements=hotword_replacements,
        )
        if _manual_editor_should_reveal_asr_source_text(text, asr_text):
            asr_text = _manual_editor_trim_asr_reveal_text_to_source_fragment(
                asr_text,
                payload,
                previous_item=rows[-1] if rows else None,
                next_item=None,
            )
            payload["transcript_text_raw"] = raw_asr_text
            payload["transcript_text"] = asr_text
        rows.append(payload)
        cursor = max(cursor, search_cursor)
    return rows


def _manual_editor_trim_asr_reveal_text_to_source_fragment(
    asr_text: str,
    item: dict[str, Any],
    *,
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
) -> str:
    final_text = _manual_editor_final_subtitle_text(item)
    if not final_text:
        return asr_text
    normalized_asr = _manual_editor_apply_source_text_corrections(asr_text)
    if not normalized_asr:
        return final_text
    if final_text not in normalized_asr:
        return final_text if previous_item is not None or next_item is not None else normalized_asr
    prefix, suffix = normalized_asr.split(final_text, 1)
    previous_text = _manual_editor_final_subtitle_text(previous_item or {})
    next_text = _manual_editor_final_subtitle_text(next_item or {})
    prefix = _manual_editor_trim_asr_prefix_overlap_with_previous(prefix, previous_text)
    suffix = _manual_editor_trim_asr_suffix_overlap_with_next(suffix, next_text)
    return f"{prefix}{final_text}{suffix}"


def _manual_editor_trim_asr_suffix_overlap_with_next(suffix: str, next_text: str) -> str:
    if not suffix or not next_text:
        return suffix
    next_key = _manual_editor_compact_text_key(next_text)
    for offset in range(len(suffix)):
        overlap = suffix[offset:]
        overlap_key = _manual_editor_compact_text_key(overlap)
        if len(overlap_key) >= 2 and next_key.startswith(overlap_key):
            return suffix[:offset]
    return suffix


def _manual_editor_trim_asr_prefix_overlap_with_previous(prefix: str, previous_text: str) -> str:
    if not prefix or not previous_text:
        return prefix
    previous_key = _manual_editor_compact_text_key(previous_text)
    for end in range(len(prefix), 0, -1):
        overlap = prefix[:end]
        overlap_key = _manual_editor_compact_text_key(overlap)
        if len(overlap_key) >= 2 and previous_key.endswith(overlap_key):
            return prefix[end:]
    return prefix


def _manual_editor_transcript_source_rows(
    transcript_rows: list[TranscriptSegment],
    *,
    context_text: str,
) -> list[dict[str, Any]]:
    latest_version = max((int(row.version or 1) for row in transcript_rows), default=1)
    rows: list[dict[str, Any]] = []
    for fallback_index, row in enumerate(
        sorted(
            [item for item in transcript_rows if int(item.version or 1) == latest_version],
            key=lambda item: (
                int(item.segment_index or 0),
                float(item.start_time or 0.0),
                float(item.end_time or 0.0),
            ),
        )
    ):
        final_text = _manual_editor_source_editable_text(row.text)
        if not final_text:
            continue
        row_words = _manual_editor_drop_redundant_synthetic_words(list(row.words_json or []))
        index = int(row.segment_index if row.segment_index is not None else fallback_index)
        rows.append(
            {
                "index": index,
                "source_index": index,
                "source_indexes": [index],
                "start_time": float(row.start_time),
                "end_time": float(row.end_time),
                "text_raw": str(row.text or ""),
                "text_norm": final_text,
                "text_final": final_text,
                "timing_text": final_text,
                "words": [
                    dict(word)
                    for word in row_words
                    if isinstance(word, dict)
                ],
                "display_suppressed_reason": getattr(row, "display_suppressed_reason", None),
                "projection_source": "transcript_segment",
            }
        )
    return rows


def _manual_editor_subtitle_item_source_rows(
    subtitle_rows: list[SubtitleItem],
    *,
    context_text: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in subtitle_rows:
        item_payload = {
            "text_raw": item.text_raw,
            "text_norm": item.text_norm,
            "text_final": item.text_final,
            "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
        }
        raw_text = _manual_editor_source_editable_text(subtitle_raw_rule_text(item_payload))
        norm_text = _manual_editor_source_editable_text(subtitle_canonical_rule_text(item_payload))
        final_text = _manual_editor_source_editable_text(subtitle_display_rule_text(item_payload))
        if not final_text:
            continue
        rows.append(
            {
                "index": int(item.item_index),
                "source_index": int(item.item_index),
                "source_indexes": [int(item.item_index)],
                "start_time": float(item.start_time),
                "end_time": float(item.end_time),
                "text_raw": raw_text,
                "text_norm": norm_text,
                "text_final": final_text,
                "timing_text": final_text,
                "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
                "projection_source": "subtitle_item",
            }
        )
    return rows


def _manual_editor_source_segmentation_quality(rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {
            "penalty": 10**9,
            "wordless_rows": 0,
            "overlong_rows": 0,
            "suspicious_boundaries": 0,
            "low_confidence_windows": 0,
            "fragment_starts": 0,
            "fragment_ends": 0,
        }
    entries: list[SubtitleEntry] = []
    wordless_rows = 0
    overlong_rows = 0
    for index, row in enumerate(rows):
        text = _manual_editor_final_subtitle_text(row)
        words = [
            dict(word)
            for word in list(row.get("words") or [])
            if isinstance(word, dict)
        ]
        if not words:
            wordless_rows += 1
        try:
            start_time = float(row.get("start_time", row.get("start", 0.0)) or 0.0)
            end_time = float(row.get("end_time", row.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            start_time = 0.0
            end_time = 0.0
        if len(subtitle_display_units(text)) > 32 or max(0.0, end_time - start_time) > 6.0:
            overlong_rows += 1
        entries.append(
            SubtitleEntry(
                index=index,
                start=start_time,
                end=end_time,
                text_raw=text,
                text_norm=text,
                words=tuple(words),
            )
        )
    analysis = analyze_subtitle_segmentation(entries)
    penalty = (
        wordless_rows * 12
        + overlong_rows * 10
        + analysis.suspicious_boundary_count * 6
        + analysis.low_confidence_window_count * 4
        + analysis.fragment_start_count * 3
        + analysis.fragment_end_count * 3
    )
    return {
        "penalty": penalty,
        "wordless_rows": wordless_rows,
        "overlong_rows": overlong_rows,
        "suspicious_boundaries": analysis.suspicious_boundary_count,
        "low_confidence_windows": analysis.low_confidence_window_count,
        "fragment_starts": analysis.fragment_start_count,
        "fragment_ends": analysis.fragment_end_count,
    }


def _manual_editor_choose_source_subtitle_rows(
    candidates: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    preference_rank = {"transcript_segment": 0, "canonical_transcript": 1, "subtitle_item": 2}
    scored_candidates: list[tuple[tuple[int, int, int], list[dict[str, Any]]]] = []
    for basis, rows in candidates:
        if not rows:
            continue
        quality = _manual_editor_source_segmentation_quality(rows)
        scored_candidates.append(
            (
                (
                    int(quality["penalty"]),
                    preference_rank.get(basis, 99),
                    len(rows),
                ),
                rows,
            )
        )
    if not scored_candidates:
        return []
    scored_candidates.sort(key=lambda item: item[0])
    return scored_candidates[0][1]


def _manual_editor_projection_rows_as_source_rows(
    projection_rows: list[dict[str, Any]],
    *,
    projection_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    transcript_layer = str((projection_data or {}).get("transcript_layer") or "").strip() or "canonical_transcript"
    rows: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(list(projection_rows or [])):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", fallback_index) or fallback_index)
        except (TypeError, ValueError):
            index = fallback_index
        try:
            start_time = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            end_time = float(item.get("end_time", item.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            continue
        row_start_time = start_time
        row_end_time = end_time
        source_start_time = _coerce_timing_value(item.get("source_overlap_start_time"))
        source_end_time = _coerce_timing_value(item.get("source_overlap_end_time"))
        if (
            source_start_time is not None
            and source_end_time is not None
            and source_end_time > source_start_time
        ):
            start_time = source_start_time
            end_time = source_end_time
        preserve_projection_words = not (
            source_start_time is not None
            and source_end_time is not None
            and source_end_time > source_start_time
            and (
                abs(start_time - row_start_time) > 0.02
                or abs(end_time - row_end_time) > 0.02
            )
        )
        text_raw = subtitle_raw_rule_text(item)
        text_norm = subtitle_canonical_rule_text(item)
        text_final = subtitle_display_rule_text(item)
        timing_text = str(item.get("timing_text") or text_norm or text_raw).strip()
        if not timing_text and not text_final and not text_norm and not text_raw:
            continue
        rows.append(
            {
                "index": index,
                "source_index": index,
                "source_indexes": [index],
                "start_time": start_time,
                "end_time": end_time,
                "text_raw": text_raw,
                "text_norm": text_norm,
                "text_final": text_final,
                "timing_text": timing_text,
                "words": [
                    dict(word)
                    for word in drop_redundant_synthetic_word_payloads(list(item.get("words") or []))
                    if isinstance(word, dict)
                ] if preserve_projection_words else [],
                "display_suppressed_reason": str(item.get("display_suppressed_reason") or "").strip() or None,
                "projection_source": str(item.get("projection_source") or transcript_layer),
                "segmentation_locked": True,
            }
        )
    rows.sort(
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
            int(item.get("index", 0) or 0),
        )
    )
    return rows


def _manual_editor_projection_rows_are_output_timeline_rows(
    projected_subtitles: list[dict[str, Any]],
) -> bool:
    for item in projected_subtitles:
        if not isinstance(item, dict):
            continue
        source_start = _coerce_timing_value(item.get("source_overlap_start_time"))
        source_end = _coerce_timing_value(item.get("source_overlap_end_time"))
        if source_start is None or source_end is None or source_end <= source_start:
            continue
        row_start = _coerce_timing_value(item.get("start_time", item.get("start")))
        row_end = _coerce_timing_value(item.get("end_time", item.get("end")))
        if row_start is None or row_end is None or row_end <= row_start:
            continue
        if abs(row_start - source_start) > 0.02 or abs(row_end - source_end) > 0.02:
            return True
    return False


async def _load_manual_editor_source_subtitle_dicts(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    latest_projection_rows: list[dict[str, Any]] | None = None,
    latest_projection_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from roughcut.pipeline.steps import _load_latest_current_canonical_transcript_data

    job = await session.get(Job, job_id)
    context_parts = [str(getattr(job, "source_name", "") or "")]
    if latest_projection_rows is None or latest_projection_data is None:
        latest_projection_rows, latest_projection_data = await _load_manual_editor_latest_subtitle_projection_entries(
            session,
            job_id=job_id,
            fallback_items=None,
        )
    else:
        latest_projection_rows = list(latest_projection_rows)
        latest_projection_data = dict(latest_projection_data)
    projection_fallback_source_rows: list[dict[str, Any]] = []
    if latest_projection_rows:
        cleaned_projection_rows = preserve_subtitle_payloads(latest_projection_rows, drop_empty=True)
        split_profile = (
            latest_projection_data.get("split_profile")
            if isinstance(latest_projection_data.get("split_profile"), dict)
            else {}
        )
        transcript_layer = str(latest_projection_data.get("transcript_layer") or "").strip()
        if (
            transcript_layer not in {"", "subtitle_item"}
            and not _manual_editor_projection_has_suspicious_subtitle_timing(
                cleaned_projection_rows,
                split_profile=split_profile,
            )
        ):
            projection_fallback_source_rows = _manual_editor_projection_rows_as_source_rows(
                cleaned_projection_rows,
                projection_data=latest_projection_data,
            )
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
    if canonical_layer and not canonical_transcript_data_is_current(canonical_layer):
        canonical_layer = await _load_latest_current_canonical_transcript_data(
            session,
            job_id=job_id,
        )
    context_parts.extend(
        subtitle_semantic_item_text(
            segment,
            generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
        )
        for segment in list(canonical_layer.get("segments") or [])
        if isinstance(segment, dict)
    )
    context_text = "\n".join(part for part in context_parts if part)

    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id)
        .order_by(TranscriptSegment.version.desc(), TranscriptSegment.segment_index.asc())
    )
    transcript_rows = list(transcript_result.scalars().all())
    source_row_candidates: list[tuple[str, list[dict[str, Any]]]] = []
    # Manual editor fallback rows must preserve upstream segmentation ownership.
    # If projection is unavailable, surface raw source rows instead of re-splitting here.
    if transcript_rows:
        sanitize_transcript_segment_word_rows(transcript_rows)
        if not context_text:
            context_text = "\n".join([str(getattr(job, "source_name", "") or ""), *(row.text for row in transcript_rows)])
        transcript_source_rows = _manual_editor_transcript_source_rows(transcript_rows, context_text=context_text)
        if transcript_source_rows:
            source_row_candidates.append(
                (
                    "transcript_segment",
                    transcript_source_rows,
                )
            )

    canonical_rows = _manual_editor_canonical_segment_source_rows(canonical_layer, context_text=context_text)
    if canonical_rows:
        source_row_candidates.append(
            (
                "canonical_transcript",
                canonical_rows,
            )
        )

    result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_rows = list(result.scalars().all())
    if not context_text:
        context_parts.extend(
            subtitle_canonical_rule_text(
                {
                    "text_raw": item.text_raw,
                    "text_norm": item.text_norm,
                    "text_final": item.text_final,
                    "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
                }
            )
            for item in subtitle_rows
        )
        context_text = "\n".join(part for part in context_parts if part)
    subtitle_item_rows = _manual_editor_subtitle_item_source_rows(subtitle_rows, context_text=context_text)
    if subtitle_item_rows:
        source_row_candidates.append(
            (
                "subtitle_item",
                subtitle_item_rows,
            )
        )
    chosen_rows = _manual_editor_choose_source_subtitle_rows(
        source_row_candidates,
    )
    if chosen_rows:
        return chosen_rows
    if projection_fallback_source_rows:
        return projection_fallback_source_rows
    return []


def _manual_editor_subtitle_payload(item: dict[str, Any], *, index: int) -> ManualEditorSubtitleOut:
    source_final = _manual_editor_editable_final_subtitle_text(item)
    explicit_text_final = str(item.get("text_final") or "")
    if (
        item.get("text_norm") is None
        and item.get("text_raw") is not None
        and explicit_text_final
    ):
        text_final = _manual_editor_editable_text(explicit_text_final)
    else:
        text_final = source_final
    transcript_text = _manual_editor_source_editable_text(item.get("transcript_text"))
    canonical_source_text = text_final or _manual_editor_display_source_text(item, final_text=text_final)
    try:
        start_time = max(0.0, float(item.get("start_time", item.get("start", 0.0)) or 0.0))
        end_time = max(0.0, float(item.get("end_time", item.get("end", start_time)) or start_time))
        if end_time < start_time:
            end_time = start_time
    except (TypeError, ValueError):
        start_time = 0.0
        end_time = 0.0
    raw_item_index = item.get("index")
    try:
        item_index = int(raw_item_index) if raw_item_index is not None else int(index)
    except (TypeError, ValueError):
        item_index = int(index)
    raw_source_index = item.get("source_index", item.get("item_index"))
    try:
        source_index = int(raw_source_index) if raw_source_index is not None else item_index
    except (TypeError, ValueError):
        source_index = int(index)
    source_indexes: list[int] = []
    for raw_index in list(item.get("source_indexes") or []):
        try:
            source_indexes.append(int(raw_index))
        except (TypeError, ValueError):
            continue
    if source_index not in source_indexes:
        source_indexes.insert(0, source_index)
    word_payloads = [
        word.model_dump()
        for raw_word in list(item.get("words") or [])
        if isinstance(raw_word, dict)
        if (word := _manual_editor_word_payload(raw_word)) is not None
    ]
    normalized_word_payloads = _manual_editor_normalize_word_payloads_for_text(
        word_payloads,
        transcript_text or canonical_source_text or text_final,
    )
    alignment_item = {**item, "words": normalized_word_payloads}
    raw_alignment_token_payloads = subtitle_span_token_payloads(alignment_item)
    alignment_tokens = [
        ManualEditorSubtitleSpanTokenOut(**token)
        for token in _manual_editor_normalize_alignment_token_payloads(
            raw_alignment_token_payloads,
            canonical_text=canonical_source_text or text_final,
        )
    ]
    alignment_diagnostics = subtitle_span_alignment_diagnostics(item)
    source_overlap_start_time = _coerce_timing_value(item.get("source_overlap_start_time"))
    if source_overlap_start_time is not None:
        source_overlap_start_time = max(0.0, source_overlap_start_time)
    source_overlap_end_time = _coerce_timing_value(item.get("source_overlap_end_time"))
    if source_overlap_end_time is not None:
        source_overlap_end_time = max(0.0, source_overlap_end_time)
    return ManualEditorSubtitleOut(
        index=item_index,
        source_index=source_index,
        source_indexes=source_indexes,
        projection_source=str(item.get("projection_source") or "").strip() or None,
        source_fragment_index=(
            _coerce_int(item.get("source_fragment_index"))
            if item.get("source_fragment_index") is not None
            else None
        ),
        source_fragment_count=(
            _coerce_int(item.get("source_fragment_count"))
            if item.get("source_fragment_count") is not None
            else None
        ),
        source_overlap_start_time=(
            round(source_overlap_start_time, 3) if source_overlap_start_time is not None else None
        ),
        source_overlap_end_time=(
            round(source_overlap_end_time, 3)
            if source_overlap_end_time is not None
            else None
        ),
        source_text_full=_manual_editor_source_editable_text(item.get("source_text_full")) or None,
        start_time=round(start_time, 3),
        end_time=round(end_time, 3),
        text_raw=_manual_editor_raw_editable_text(item.get("text_raw")) or None,
        text_norm=_manual_editor_raw_editable_text(item.get("text_norm")) or None,
        text_final=text_final,
        transcript_text_raw=_manual_editor_raw_editable_text(item.get("transcript_text_raw")) or None,
        transcript_text=transcript_text or None,
        timing_text=_manual_editor_source_editable_text(item.get("timing_text")) or None,
        display_suppressed_reason=str(item.get("display_suppressed_reason") or "").strip() or None,
        words=[ManualEditorWordOut(**word) for word in normalized_word_payloads],
        alignment_tokens=alignment_tokens,
        alignment_diagnostics=alignment_diagnostics,
    )


def _source_ranges_for_output_range(
    output_start: float,
    output_end: float,
    keep_segments: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    return source_ranges_for_output_range(output_start, output_end, keep_segments)


def _annotate_manual_projected_subtitle_sources(
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return annotate_projected_subtitle_sources(projected_subtitles, source_subtitles, keep_segments)


def _manual_projection_has_source_text_mismatch(
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
) -> bool:
    return projection_has_source_text_mismatch(projected_subtitles, source_subtitles)


def _manual_editor_source_fallback_projection_items(
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return remap_subtitles_to_timeline(
        _clean_manual_editor_subtitle_projection(
            source_subtitles,
            drop_empty=False,
            collapse_repeats=False,
        ),
        keep_segments,
    )


def _manual_editor_subtitle_source_indexes(item: dict[str, Any]) -> set[int]:
    indexes: set[int] = set()
    for raw_index in list(item.get("source_indexes") or []):
        try:
            indexes.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    raw_source_index = item.get("source_index", item.get("index"))
    try:
        indexes.add(int(raw_source_index))
    except (TypeError, ValueError):
        pass
    return indexes


def _manual_editor_projected_subtitles_have_duplicate_source_overlap(
    projected_subtitles: list[dict[str, Any]],
) -> bool:
    rows = sorted(
        [item for item in projected_subtitles if isinstance(item, dict)],
        key=lambda item: (
            float(item.get("start_time", item.get("start", 0.0)) or 0.0),
            float(item.get("end_time", item.get("end", 0.0)) or 0.0),
        ),
    )
    for index in range(1, len(rows)):
        previous = rows[index - 1]
        current = rows[index]
        previous_indexes = _manual_editor_subtitle_source_indexes(previous)
        current_indexes = _manual_editor_subtitle_source_indexes(current)
        if not previous_indexes or previous_indexes.isdisjoint(current_indexes):
            continue
        try:
            previous_start = float(previous.get("start_time", previous.get("start", 0.0)) or 0.0)
            previous_end = float(previous.get("end_time", previous.get("end", previous_start)) or previous_start)
            current_start = float(current.get("start_time", current.get("start", 0.0)) or 0.0)
            current_end = float(current.get("end_time", current.get("end", current_start)) or current_start)
        except (TypeError, ValueError):
            continue
        overlap = min(previous_end, current_end) - max(previous_start, current_start)
        min_duration = min(max(0.001, previous_end - previous_start), max(0.001, current_end - current_start))
        if overlap / min_duration >= 0.72:
            return True
    return False


def _manual_editor_projection_should_use_source_fallback(
    projected_subtitles: list[dict[str, Any]],
    *,
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> bool:
    if not projected_subtitles or not source_subtitles or not keep_segments:
        return False
    if _manual_editor_projected_subtitles_have_duplicate_source_overlap(projected_subtitles):
        return True
    validation = validate_projected_subtitles_against_transcript(
        projected_subtitles,
        transcript_segments=source_subtitles,
        keep_segments=keep_segments,
    )
    return _manual_editor_transcript_projection_blocking_is_significant(validation)


def _manual_editor_projection_contract_locked(
    *,
    manual_projection_items: list[dict[str, Any]],
    raw_projection_rows: list[dict[str, Any]],
    projection_data: dict[str, Any] | None,
    draft_active: bool,
    manual_projection_suspicious: bool,
) -> bool:
    if manual_projection_items and not draft_active and not manual_projection_suspicious:
        return True
    transcript_layer = str((projection_data or {}).get("transcript_layer") or "").strip()
    return bool(
        raw_projection_rows
        and transcript_layer not in {"", "subtitle_item"}
        and _manual_editor_projection_data_is_current(projection_data)
    )


def _manual_editor_should_apply_source_projection_fallback(
    projected_subtitles: list[dict[str, Any]],
    *,
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
    manual_projection_items: list[dict[str, Any]],
    raw_projection_rows: list[dict[str, Any]],
    projection_data: dict[str, Any] | None,
    draft_active: bool,
    manual_projection_suspicious: bool,
) -> bool:
    if not _manual_editor_projection_should_use_source_fallback(
        projected_subtitles,
        source_subtitles=source_subtitles,
        keep_segments=keep_segments,
    ):
        return False
    return not _manual_editor_projection_contract_locked(
        manual_projection_items=manual_projection_items,
        raw_projection_rows=raw_projection_rows,
        projection_data=projection_data,
        draft_active=draft_active,
        manual_projection_suspicious=manual_projection_suspicious,
    )


def _manual_editor_transcript_projection_blocking_is_significant(validation: dict[str, Any] | None) -> bool:
    payload = validation if isinstance(validation, dict) else {}
    if not bool(payload.get("blocking")):
        return False
    kept_count = max(0, int(payload.get("kept_speech_unit_count") or 0))
    blocking_count = max(0, int(payload.get("blocking_issue_count") or 0))
    if blocking_count <= 0:
        return False
    blocking_examples = [
        item
        for item in list(payload.get("blocking_examples") or [])
        if isinstance(item, dict)
    ]
    if any(
        str(item.get("type") or "").strip() == "speech_segment"
        or len(str(item.get("text") or "").strip()) >= 2
        or float(item.get("duration_sec") or 0.0) >= 0.6
        for item in blocking_examples
    ):
        return True
    if kept_count <= 120:
        return True
    return (blocking_count / max(1, kept_count)) >= 0.03


def _manual_editor_split_long_subtitle_rows(
    subtitles: list[dict[str, Any]],
    *,
    reindex_fragments: bool = False,
    context_text: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_index = max(
        (
            int(item.get("index")) if item.get("index") is not None else -1
            for item in subtitles
            if isinstance(item, dict)
        ),
        default=-1,
    ) + 1
    for item in subtitles:
        if not isinstance(item, dict):
            continue
        text = _manual_editor_final_subtitle_text(item)
        segmentation_text = _manual_editor_timing_text(item, final_text=text) or text
        try:
            start_time = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            end_time = float(item.get("end_time", item.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            rows.append(dict(item))
            continue
        timed_words = [
            dict(word)
            for word in list(item.get("words") or [])
            if isinstance(word, dict) and str(word.get("word") or word.get("raw_text") or word.get("text") or "").strip()
        ]
        pieces: list[dict[str, Any]]
        pieces_have_word_segmented_timings = False
        split_strategy = _MANUAL_EDITOR_SPLIT_STRATEGY_NO_SPLIT
        if timed_words:
            segmentation_result = segment_subtitles(
                [
                    SimpleNamespace(
                        segment_index=int(item.get("index", len(rows)) or len(rows)),
                        start_time=start_time,
                        end_time=end_time,
                        text=segmentation_text,
                        words_json=timed_words,
                    )
                ],
                max_chars=32,
                max_duration=6.0,
            )
            pieces = [
                {
                    "start_time": float(getattr(entry, "start", start_time) or start_time),
                    "end_time": float(getattr(entry, "end", end_time) or end_time),
                    "text_raw": str(getattr(entry, "text_raw", None) or ""),
                    "text_norm": str(getattr(entry, "text_norm", None) or ""),
                    "text": str(getattr(entry, "text_raw", None) or getattr(entry, "text_norm", None) or ""),
                    "timing_text": str(getattr(entry, "text_raw", None) or getattr(entry, "text_norm", None) or ""),
                }
                for entry in list(segmentation_result.entries or [])
                if str(
                    getattr(entry, "text_norm", None)
                    or getattr(entry, "text_raw", None)
                    or ""
                ).strip()
            ]
            pieces_have_word_segmented_timings = bool(pieces)
            if pieces:
                split_strategy = _MANUAL_EDITOR_SPLIT_STRATEGY_WORD_TIMED
            if pieces and not _manual_editor_split_pieces_cover_source_text(segmentation_text, pieces):
                split_strategy = _MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_SEGMENTATION_MISMATCH
                pieces = split_subtitle_display_item(
                    start_time=start_time,
                    end_time=end_time,
                    text=segmentation_text,
                    max_duration_sec=6.0,
                    max_chars=32,
                )
                for piece in pieces:
                    piece["timing_text"] = normalize_flashlight_model_alias_text(str(piece.get("text") or ""))
                pieces_have_word_segmented_timings = False
            if not pieces:
                split_strategy = _MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_NO_SEGMENTATION_OUTPUT
                pieces = split_subtitle_display_item(
                    start_time=start_time,
                    end_time=end_time,
                    text=segmentation_text,
                    max_duration_sec=6.0,
                    max_chars=32,
                )
                for piece in pieces:
                    piece["timing_text"] = normalize_flashlight_model_alias_text(str(piece.get("text") or ""))
                pieces_have_word_segmented_timings = False
        else:
            split_strategy = _MANUAL_EDITOR_SPLIT_STRATEGY_DISPLAY_NO_WORDS
            pieces = split_subtitle_display_item(
                start_time=start_time,
                end_time=end_time,
                text=segmentation_text,
                max_duration_sec=6.0,
                max_chars=32,
            )
            for piece in pieces:
                piece["timing_text"] = normalize_flashlight_model_alias_text(str(piece.get("text") or ""))
                piece["text"] = normalize_flashlight_model_alias_text(str(piece.get("text") or ""))

        for piece in pieces:
            piece["text"] = normalize_flashlight_model_alias_text(str(piece.get("text") or ""))
            piece["timing_text"] = normalize_flashlight_model_alias_text(
                str(piece.get("timing_text") or piece.get("text") or "")
            )
        original_piece_timing_texts = [str(piece.get("timing_text") or piece.get("text") or "") for piece in pieces]
        pieces = _manual_editor_rebalance_split_leading_particles(pieces)
        pieces = _manual_editor_rebalance_split_dangling_boundaries(pieces)
        rebalanced_piece_timing_texts = [str(piece.get("timing_text") or piece.get("text") or "") for piece in pieces]
        split_boundary_rebalanced = rebalanced_piece_timing_texts != original_piece_timing_texts
        split_piece_timing_source = (
            "segmented_word_timing"
            if pieces_have_word_segmented_timings and not split_boundary_rebalanced
            else "recomputed_from_words"
            if len(pieces) > 1
            else "row_bounds"
        )
        if len(pieces) <= 1:
            row = _manual_editor_tighten_source_row_to_display_words(dict(item), fallback_text=text)
            row["split_strategy"] = split_strategy
            row["split_attempted"] = split_strategy != _MANUAL_EDITOR_SPLIT_STRATEGY_NO_SPLIT
            row["split_boundary_rebalanced"] = bool(split_boundary_rebalanced)
            row["split_piece_timing_source"] = split_piece_timing_source
            rows.append(row)
            continue
        piece_timings = (
            [None for _piece in pieces]
            if pieces_have_word_segmented_timings and not split_boundary_rebalanced
            else _manual_editor_split_piece_timings_from_words(
                item,
                [
                    {"text": str(piece.get("timing_text") or piece.get("text") or "")}
                    for piece in pieces
                ],
            )
        )
        original_index = int(item.get("index")) if item.get("index") is not None else next_index
        next_index = max(next_index, original_index + 1)
        for fragment_index, piece in enumerate(pieces):
            row = dict(item)
            word_timing = piece_timings[fragment_index] if fragment_index < len(piece_timings) else None
            piece_start = float(word_timing[0]) if word_timing is not None else float(piece["start_time"])
            piece_end = float(word_timing[1]) if word_timing is not None else float(piece["end_time"])
            if fragment_index == 0:
                row["index"] = original_index
            else:
                row["index"] = next_index
                next_index += 1
            row["source_fragment_index"] = fragment_index
            row["source_fragment_count"] = len(pieces)
            row["source_text_full"] = text
            row["source_overlap_start_time"] = piece_start
            row["source_overlap_end_time"] = piece_end
            row["start_time"] = piece_start
            row["end_time"] = piece_end
            row["words"] = [
                dict(word)
                for word in list(item.get("words") or [])
                if isinstance(word, dict)
                and _manual_editor_word_belongs_to_range(word, start=piece_start, end=piece_end)
            ]
            piece_raw_text = str(piece.get("text_raw") or piece.get("timing_text") or piece.get("text") or "")
            piece_canonical_text = str(piece.get("text_norm") or piece.get("timing_text") or piece.get("text") or piece_raw_text)
            if str(item.get("timing_text") or "").strip():
                piece_display_text = str(piece.get("text") or piece.get("text_norm") or piece.get("text_raw") or "")
            else:
                piece_display_text = str(piece.get("text_norm") or piece.get("text") or piece.get("text_raw") or "")
            if "text_raw" in row:
                row["text_raw"] = piece_raw_text
            if "text_norm" in row or "text_norm" in piece or piece_canonical_text != piece_raw_text:
                row["text_norm"] = piece_canonical_text
            if "text_final" in row:
                row["text_final"] = piece_display_text
            if "text" in row:
                row["text"] = piece_display_text
            if "transcript_text" in row or "text_norm" in piece or piece_canonical_text != piece_display_text:
                row["transcript_text"] = piece_canonical_text
            if "display_source_text" in row:
                row["display_source_text"] = piece_display_text
            row["timing_text"] = str(piece.get("timing_text") or piece["text"])
            if not any(key in row for key in ("text_raw", "text_norm", "text_final", "text")):
                row["text_final"] = piece_display_text
            if reindex_fragments:
                row["source_index"] = int(row["index"])
                row["source_indexes"] = [int(row["index"])]
            row["split_strategy"] = split_strategy
            row["split_attempted"] = split_strategy != _MANUAL_EDITOR_SPLIT_STRATEGY_NO_SPLIT
            row["split_boundary_rebalanced"] = bool(split_boundary_rebalanced)
            row["split_piece_timing_source"] = split_piece_timing_source
            row = _manual_editor_tighten_source_row_to_display_words(row, fallback_text=piece_display_text)
            rows.append(row)
    rows.sort(
        key=lambda item: (
            float(item.get("start_time", item.get("start", 0.0)) or 0.0),
            float(item.get("end_time", item.get("end", 0.0)) or 0.0),
            int(item.get("index", 0) or 0),
        )
    )
    if reindex_fragments:
        for new_index, row in enumerate(rows):
            row["index"] = new_index
            row["source_index"] = new_index
            row["source_indexes"] = [new_index]
    return rows


def _manual_editor_source_row_split_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strategy_counts: dict[str, int] = {}
    attempted_row_count = 0
    fragmented_row_count = 0
    fragment_count = 0
    boundary_rebalanced_count = 0
    recomputed_timing_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        strategy = str(row.get("split_strategy") or "").strip()
        if not strategy or strategy == _MANUAL_EDITOR_SPLIT_STRATEGY_NO_SPLIT:
            continue
        fragment_index = _coerce_int(row.get("source_fragment_index"))
        if fragment_index not in {None, 0}:
            continue
        attempted_row_count += 1
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        source_fragment_count = max(1, int(_coerce_int(row.get("source_fragment_count")) or 1))
        if source_fragment_count > 1:
            fragmented_row_count += 1
            fragment_count += source_fragment_count
        if bool(row.get("split_boundary_rebalanced")):
            boundary_rebalanced_count += 1
        if str(row.get("split_piece_timing_source") or "").strip() == "recomputed_from_words":
            recomputed_timing_count += 1
    return {
        "attempted_row_count": attempted_row_count,
        "fragmented_row_count": fragmented_row_count,
        "fragment_count": fragment_count,
        "boundary_rebalanced_count": boundary_rebalanced_count,
        "recomputed_timing_count": recomputed_timing_count,
        "strategy_counts": strategy_counts,
    }


_MANUAL_EDITOR_MOVABLE_LEADING_PARTICLE_RE = re.compile(r"^([啊吧呢嘛呀呐哦哎诶欸噢喔][，,、。！？!\?…\s]*)")
_MANUAL_EDITOR_DANGLING_PREFIX_TAILS = ("非", "很", "太", "更", "最", "挺", "超", "好")
_MANUAL_EDITOR_CN_DIGIT_UNITS = frozenset("零〇一二两三四五六七八九十0123456789")
_MANUAL_EDITOR_BOUNDARY_PARTICLE_UNITS = frozenset("啊吧呢嘛呀呐哦哎诶欸噢喔")


def _manual_editor_rebalance_split_leading_particles(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(pieces) <= 1:
        return pieces
    rows = [dict(piece) for piece in pieces]
    for index in range(1, len(rows)):
        current_text = str(rows[index].get("text") or "")
        match = _MANUAL_EDITOR_MOVABLE_LEADING_PARTICLE_RE.match(current_text)
        if not match:
            continue
        previous_text = str(rows[index - 1].get("text") or "")
        if not _manual_editor_compact_text_key(previous_text):
            continue
        moved = match.group(1)
        remaining = current_text[match.end():]
        if not _manual_editor_compact_text_key(remaining):
            continue
        rows[index - 1]["text"] = f"{previous_text}{moved}"
        rows[index]["text"] = remaining
        previous_timing_text = str(rows[index - 1].get("timing_text") or previous_text)
        current_timing_text = str(rows[index].get("timing_text") or current_text)
        rows[index - 1]["timing_text"] = f"{previous_timing_text}{moved}"
        rows[index]["timing_text"] = current_timing_text[match.end():]
    return rows


def _manual_editor_rebalance_split_dangling_boundaries(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(pieces) <= 1:
        return pieces
    rows = [dict(piece) for piece in pieces]
    for _pass in range(4):
        changed = False
        for index in range(1, len(rows)):
            previous_units = subtitle_display_units(str(rows[index - 1].get("text") or ""))
            current_units = subtitle_display_units(str(rows[index].get("text") or ""))
            move_count = _manual_editor_leading_units_to_move_for_split_boundary(previous_units, current_units)
            if move_count <= 0 or move_count >= len(current_units):
                continue
            rows[index - 1]["text"] = "".join([*previous_units, *current_units[:move_count]])
            rows[index]["text"] = "".join(current_units[move_count:])
            previous_timing_units = subtitle_display_units(str(rows[index - 1].get("timing_text") or ""))
            current_timing_units = subtitle_display_units(str(rows[index].get("timing_text") or ""))
            rows[index - 1]["timing_text"] = "".join([*previous_timing_units, *current_timing_units[:move_count]])
            rows[index]["timing_text"] = "".join(current_timing_units[move_count:])
            changed = True
        if not changed:
            break
    for index in range(1, len(rows)):
        previous_units = subtitle_display_units(str(rows[index - 1].get("text") or ""))
        current_units = subtitle_display_units(str(rows[index].get("text") or ""))
        move_count = _manual_editor_trailing_units_to_move_for_split_boundary(previous_units, current_units)
        if move_count <= 0 or move_count >= len(previous_units):
            continue
        rows[index - 1]["text"] = "".join(previous_units[:-move_count])
        rows[index]["text"] = "".join([*previous_units[-move_count:], *current_units])
        previous_timing_units = subtitle_display_units(str(rows[index - 1].get("timing_text") or ""))
        current_timing_units = subtitle_display_units(str(rows[index].get("timing_text") or ""))
        rows[index - 1]["timing_text"] = "".join(previous_timing_units[:-move_count])
        rows[index]["timing_text"] = "".join([*previous_timing_units[-move_count:], *current_timing_units])
    return rows


def _manual_editor_leading_units_to_move_for_split_boundary(previous_units: list[str], current_units: list[str]) -> int:
    if not previous_units or not current_units:
        return 0
    previous_key = "".join(subtitle_display_unit_key(unit) for unit in previous_units)
    current_keys = [subtitle_display_unit_key(unit) for unit in current_units]
    if len(previous_units) >= 14:
        return 0

    last_unit = previous_units[-1]
    last_key = subtitle_display_unit_key(last_unit)

    previous_text = "".join(previous_units)
    current_text = "".join(current_units)
    previous_compact = _manual_editor_compact_text_key(previous_text)
    current_compact = _manual_editor_compact_text_key(current_text)

    if previous_compact.endswith("E") and (current_text.startswith("C手电") or current_text.startswith("C电筒")):
        return 3

    model_tail_match = re.search(r"([A-Z]{2,6}\d?)$", previous_compact)
    if model_tail_match and current_units:
        leading_digit_units: list[str] = []
        for unit in current_units[:2]:
            if unit in _MANUAL_EDITOR_CN_DIGIT_UNITS:
                leading_digit_units.append(unit)
                continue
            break
        if leading_digit_units:
            candidate = f"{model_tail_match.group(1)}{''.join(leading_digit_units)}"
            if re.fullmatch(r"[A-Z]{2,6}\d{2,4}", candidate):
                return len(leading_digit_units)

    if re.fullmatch(r"[a-z]", last_key, re.IGNORECASE) and current_units[0] in _MANUAL_EDITOR_CN_DIGIT_UNITS:
        count = 0
        for unit in current_units[:4]:
            if unit in _MANUAL_EDITOR_CN_DIGIT_UNITS:
                count += 1
                continue
            break
        return min(count, max(0, 14 - len(previous_units)))

    if previous_key.endswith("好") and current_units[0] == "久":
        count = 1
        if len(current_units) > 1 and current_units[1] in _MANUAL_EDITOR_BOUNDARY_PARTICLE_UNITS:
            count += 1
        return min(count, max(0, 14 - len(previous_units)))

    if previous_key.endswith("非常") and current_keys[0] in {"火", "热", "好", "难", "高", "低", "强", "大", "小", "多", "少"}:
        count = 2 if len(current_keys) > 1 and current_keys[1] in {"爆", "门", "用", "受", "级", "端"} else 1
        return min(count, max(0, 14 - len(previous_units)))

    if any(previous_key.endswith(tail) for tail in _MANUAL_EDITOR_DANGLING_PREFIX_TAILS):
        if current_keys[0] in {"常", "好", "大", "高", "低", "多", "少", "快", "慢", "难", "贵", "便", "强", "弱"}:
            return 1
    return 0


def _manual_editor_trailing_units_to_move_for_split_boundary(previous_units: list[str], current_units: list[str]) -> int:
    if not previous_units or not current_units:
        return 0
    previous_text = "".join(previous_units)
    if previous_text.endswith("的迷") and current_units[0] == "你":
        return 2
    if previous_text.endswith("迷") and current_units[0] == "你":
        return 1
    return 0


def _manual_editor_split_piece_timings_from_words(
    item: dict[str, Any],
    pieces: list[dict[str, Any]],
) -> list[tuple[float, float] | None]:
    word_units: list[dict[str, Any]] = []
    for word in list(item.get("words") or []):
        if not isinstance(word, dict):
            continue
        chars = subtitle_display_units(str(word.get("word") or word.get("raw_text") or word.get("text") or ""))
        if not chars:
            continue
        try:
            start = float(word.get("start", 0.0) or 0.0)
            end = float(word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        for offset, char in enumerate(chars):
            word_units.append(
                {
                    "key": subtitle_display_unit_key(char),
                    "start": start + duration * (offset / len(chars)),
                    "end": start + duration * ((offset + 1) / len(chars)),
                }
            )
    if not word_units:
        return [None for _piece in pieces]
    unit_positions: dict[str, list[int]] = {}
    for index, unit in enumerate(word_units):
        unit_positions.setdefault(str(unit["key"]), []).append(index)

    timings: list[tuple[float, float] | None] = []
    cursor = 0
    for piece in pieces:
        piece_units = [subtitle_display_unit_key(char) for char in subtitle_display_units(str(piece.get("text") or ""))]
        matched: list[dict[str, Any]] = []
        matched_indexes: list[int] = []
        for key in piece_units:
            positions = unit_positions.get(str(key)) or []
            position_index = bisect.bisect_left(positions, cursor)
            if position_index >= len(positions):
                continue
            match_index = positions[position_index]
            matched.append(word_units[match_index])
            matched_indexes.append(match_index)
            cursor = match_index + 1
        if len(matched) / max(1, len(piece_units)) < 0.55:
            timings.append(None)
            continue
        if matched_indexes:
            matched_span = matched_indexes[-1] - matched_indexes[0] + 1
            if matched_span > 0 and len(matched_indexes) / matched_span < 0.45:
                timings.append(None)
                continue
        start = min(float(unit["start"]) for unit in matched)
        end = max(float(unit["end"]) for unit in matched)
        if end <= start:
            timings.append(None)
            continue
        if not _manual_editor_split_piece_timing_matches_expected_window(piece, start=start, end=end):
            timings.append(None)
            continue
        timings.append((round(start, 3), round(end, 3)))
    return timings


def _manual_editor_split_piece_timing_matches_expected_window(
    piece: dict[str, Any],
    *,
    start: float,
    end: float,
) -> bool:
    try:
        expected_start = float(piece.get("start_time", start) or start)
        expected_end = float(piece.get("end_time", expected_start) or expected_start)
    except (TypeError, ValueError):
        return True
    if expected_end <= expected_start:
        return True
    expected_duration = expected_end - expected_start
    actual_duration = end - start
    if actual_duration <= 0.0:
        return False
    tolerance = max(0.4, min(1.0, expected_duration * 0.35))
    if start < expected_start - tolerance or end > expected_end + tolerance:
        return False
    return actual_duration <= max(expected_duration * 1.8, expected_duration + 1.2)


def _manual_editor_tighten_source_row_to_display_words(
    item: dict[str, Any],
    *,
    fallback_text: str | None = None,
    preserve_row_timing: bool = False,
) -> dict[str, Any]:
    text = fallback_text if fallback_text is not None else _manual_editor_final_subtitle_text(item)
    raw_words = [
        dict(word)
        for word in list(item.get("words") or [])
        if isinstance(word, dict)
    ]
    if not text or not raw_words:
        return item
    display_words = _manual_editor_normalize_word_payloads_for_text(raw_words, text)
    if display_words:
        display_word_text = "".join(str(word.get("word") or "") for word in display_words)
        if _manual_editor_compact_text_key(display_word_text) != _manual_editor_compact_text_key(text):
            return item
    if display_words:
        start_time = min(float(word.get("start", 0.0) or 0.0) for word in display_words)
        end_time = max(float(word.get("end", start_time) or start_time) for word in display_words)
        if end_time > start_time:
            payload = dict(item)
            if not preserve_row_timing:
                payload["start_time"] = round(start_time, 3)
                payload["end_time"] = round(end_time, 3)
            payload["source_overlap_start_time"] = round(start_time, 3)
            payload["source_overlap_end_time"] = round(end_time, 3)
            payload["words"] = display_words
            return payload
    timing = _manual_editor_split_piece_timings_from_words(item, [{"text": text}])[0]
    if timing is None:
        return item
    start_time, end_time = timing
    if end_time <= start_time:
        return item
    payload = dict(item)
    if not preserve_row_timing:
        payload["start_time"] = round(start_time, 3)
        payload["end_time"] = round(end_time, 3)
    payload["source_overlap_start_time"] = round(start_time, 3)
    payload["source_overlap_end_time"] = round(end_time, 3)
    words = [
        dict(word)
        for word in list(item.get("words") or [])
        if isinstance(word, dict)
        and _manual_editor_word_belongs_to_range(word, start=start_time, end=end_time)
    ]
    if words:
        payload["words"] = words
    return payload


def _normalize_manual_keep_segments(
    segments: list[dict[str, Any]] | list[ManualEditorSegmentIn],
    *,
    source_duration_sec: float,
    merge_gap_sec: float = MANUAL_EDITOR_MICRO_CUT_HEAL_SEC,
) -> list[dict[str, float]]:
    raw_payloads: list[dict[str, Any]] = []
    for raw_item in segments or []:
        if isinstance(raw_item, BaseModel):
            raw_payloads.append(raw_item.model_dump())
        else:
            raw_payloads.append(dict(raw_item or {}))
    normalized = normalize_keep_segments_payloads(
        raw_payloads,
        upper_bound=max(0.0, float(source_duration_sec or 0.0)),
        merge_gap_sec=max(0.0, float(merge_gap_sec or 0.0)),
        minimum_duration_sec=0.05,
    )
    if not normalized:
        raise HTTPException(status_code=400, detail="至少保留一段有效视频。")
    return normalized


def _build_editorial_segments_from_keep_segments(
    keep_segments: list[dict[str, float]],
    *,
    source_duration_sec: float,
) -> list[dict[str, Any]]:
    return build_shared_editorial_segments_from_keep_segments(
        keep_segments,
        source_duration_sec=source_duration_sec,
        keep_reason="manual_editor_keep",
        cut_reason="manual_editor_removed",
    )


def _manual_keep_segments_from_editorial_payload(payload: dict[str, Any] | None) -> list[dict[str, float]]:
    return resolve_editorial_keep_segments(
        editorial_timeline_payload=payload,
        prefer_refine_plan=False,
        merge_gap_sec=MANUAL_EDITOR_MICRO_CUT_HEAL_SEC,
        minimum_duration_sec=0.05,
    )


def _manual_editor_base_keep_segment_dicts(
    editorial_timeline_payload: dict[str, Any] | None,
    *,
    refine_plan_payload: dict[str, Any] | None,
    editorial_timeline_id: str,
    editorial_timeline_version: int,
    source_duration_sec: float,
    prefer_refine_plan: bool = True,
) -> list[dict[str, float]]:
    resolved = resolve_editorial_keep_segments(
        editorial_timeline_payload=editorial_timeline_payload,
        refine_plan_payload=refine_plan_payload,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
        prefer_refine_plan=prefer_refine_plan,
        upper_bound=source_duration_sec if source_duration_sec > 0.0 else None,
        merge_gap_sec=MANUAL_EDITOR_MICRO_CUT_HEAL_SEC,
        minimum_duration_sec=0.05,
    )
    if resolved:
        return resolved
    return _manual_keep_segments_from_editorial_payload(editorial_timeline_payload)


def _manual_editor_frontend_managed_auto_cut_ranges(
    analysis_payload: dict[str, Any] | None,
    *,
    current_deleted_ranges: list[dict[str, float]] | None = None,
) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []
    accepted_cuts = cut_analysis_accepted_cuts(analysis_payload, resolved=True)
    _, rule_candidates = cut_analysis_candidate_items(analysis_payload, resolved=True)
    accepted_auto_items = [
        item
        for item in accepted_cuts
        if isinstance(item, dict)
        and str(item.get("reason") or "").strip() in manual_editor_frontend_managed_auto_cut_reasons()
    ]
    candidate_items: list[dict[str, Any]]
    accepted_items_authoritative = bool(accepted_auto_items)
    if accepted_items_authoritative and current_deleted_ranges is not None:
        candidate_items = []
        for item in accepted_auto_items:
            try:
                start = max(0.0, float(item.get("start", 0.0) or 0.0))
                end = max(start, float(item.get("end", start) or start))
            except (TypeError, ValueError):
                continue
            if end <= start + 0.02:
                continue
            if not _manual_editor_range_overlaps_any(
                {"start": round(start, 3), "end": round(end, 3)},
                current_deleted_ranges,
            ):
                continue
            candidate_items.append(item)
    else:
        candidate_items = accepted_auto_items if accepted_auto_items else cut_analysis_effective_applied_cuts(analysis_payload)
    for item in candidate_items:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "").strip()
        if reason not in manual_editor_frontend_managed_auto_cut_reasons():
            continue
        if not accepted_items_authoritative and not bool(item.get("auto_applied")):
            continue
        try:
            start = max(0.0, float(item.get("start", 0.0) or 0.0))
            end = max(start, float(item.get("end", start) or start))
        except (TypeError, ValueError):
            continue
        if end <= start + 0.02:
            continue
        ranges.append({"start": round(start, 3), "end": round(end, 3)})
    return ranges


def _manual_editor_deleted_ranges_from_keep_segments(
    keep_segments: list[dict[str, float]],
    *,
    source_duration_sec: float,
) -> list[dict[str, float]]:
    deleted_ranges: list[dict[str, float]] = []
    cursor = 0.0
    for segment in keep_segments:
        start = max(0.0, min(source_duration_sec, float(segment.get("start", 0.0) or 0.0)))
        end = max(start, min(source_duration_sec, float(segment.get("end", start) or start)))
        if start > cursor + 0.02:
            deleted_ranges.append({"start": round(cursor, 3), "end": round(start, 3)})
        cursor = max(cursor, end)
    if source_duration_sec > cursor + 0.02:
        deleted_ranges.append({"start": round(cursor, 3), "end": round(source_duration_sec, 3)})
    return deleted_ranges


def _manual_editor_keep_segments_from_deleted_ranges(
    deleted_ranges: list[dict[str, float]],
    *,
    source_duration_sec: float,
) -> list[dict[str, float]]:
    keep_segments: list[dict[str, float]] = []
    cursor = 0.0
    for deleted_range in deleted_ranges:
        start = max(0.0, min(source_duration_sec, float(deleted_range.get("start", 0.0) or 0.0)))
        end = max(start, min(source_duration_sec, float(deleted_range.get("end", start) or start)))
        if start > cursor + 0.02:
            keep_segments.append({"start": round(cursor, 3), "end": round(start, 3)})
        cursor = max(cursor, end)
    if source_duration_sec > cursor + 0.02:
        keep_segments.append({"start": round(cursor, 3), "end": round(source_duration_sec, 3)})
    return keep_segments


def _manual_editor_subtract_ranges(
    ranges: list[dict[str, float]],
    subtract_ranges: list[dict[str, float]],
) -> list[dict[str, float]]:
    resolved: list[dict[str, float]] = []
    ordered_subtract_ranges = sorted(
        [
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
            }
            for item in subtract_ranges
            if float(item.get("end", item.get("start", 0.0)) or 0.0)
            > float(item.get("start", 0.0) or 0.0) + 0.02
        ],
        key=lambda item: (item["start"], item["end"]),
    )
    for range_item in ranges:
        pieces = [
            {
                "start": float(range_item.get("start", 0.0) or 0.0),
                "end": float(range_item.get("end", 0.0) or 0.0),
            }
        ]
        for subtract_item in ordered_subtract_ranges:
            next_pieces: list[dict[str, float]] = []
            for piece in pieces:
                overlap_start = max(piece["start"], subtract_item["start"])
                overlap_end = min(piece["end"], subtract_item["end"])
                if overlap_end <= overlap_start + 0.02:
                    next_pieces.append(piece)
                    continue
                if overlap_start > piece["start"] + 0.02:
                    next_pieces.append({"start": piece["start"], "end": overlap_start})
                if overlap_end < piece["end"] - 0.02:
                    next_pieces.append({"start": overlap_end, "end": piece["end"]})
            pieces = next_pieces
            if not pieces:
                break
        resolved.extend(
            {"start": round(piece["start"], 3), "end": round(piece["end"], 3)}
            for piece in pieces
            if piece["end"] > piece["start"] + 0.02
        )
    return resolved


def _manual_editor_range_overlaps_any(
    range_item: dict[str, float],
    ranges: list[dict[str, float]],
    *,
    min_overlap_sec: float = 0.02,
) -> bool:
    start = float(range_item.get("start", 0.0) or 0.0)
    end = float(range_item.get("end", start) or start)
    for candidate in ranges:
        overlap = min(end, float(candidate.get("end", 0.0) or 0.0)) - max(start, float(candidate.get("start", 0.0) or 0.0))
        if overlap > min_overlap_sec:
            return True
    return False


def _manual_editor_restore_frontend_managed_auto_cuts(
    keep_segments: list[Any],
    *,
    analysis_payload: dict[str, Any] | None,
    source_duration_sec: float,
) -> list[dict[str, float]]:
    if source_duration_sec <= 0.05:
        return _normalize_manual_keep_segments(
            keep_segments,
            source_duration_sec=source_duration_sec,
            merge_gap_sec=0.0,
        )
    normalized_keep_segments = _normalize_manual_keep_segments(
        keep_segments,
        source_duration_sec=source_duration_sec,
        merge_gap_sec=0.0,
    )
    deleted_ranges = _manual_editor_deleted_ranges_from_keep_segments(
        normalized_keep_segments,
        source_duration_sec=source_duration_sec,
    )
    managed_ranges = _manual_editor_frontend_managed_auto_cut_ranges(
        analysis_payload,
        current_deleted_ranges=deleted_ranges,
    )
    if not managed_ranges:
        return normalized_keep_segments
    remaining_deleted_ranges = _manual_editor_subtract_ranges(deleted_ranges, managed_ranges)
    restored_keep_segments = _manual_editor_keep_segments_from_deleted_ranges(
        remaining_deleted_ranges,
        source_duration_sec=source_duration_sec,
    )
    return restored_keep_segments or normalized_keep_segments


def _manual_editor_apply_frontend_managed_auto_cuts(
    keep_segments: list[Any],
    *,
    analysis_payload: dict[str, Any] | None,
    source_duration_sec: float,
    current_keep_segments: list[Any] | None = None,
) -> list[dict[str, float]]:
    if source_duration_sec <= 0.05:
        return _normalize_manual_keep_segments(
            keep_segments,
            source_duration_sec=source_duration_sec,
            merge_gap_sec=0.0,
        )
    normalized_keep_segments = _normalize_manual_keep_segments(
        keep_segments,
        source_duration_sec=source_duration_sec,
        merge_gap_sec=0.0,
    )
    current_deleted_ranges = _manual_editor_deleted_ranges_from_keep_segments(
        _normalize_manual_keep_segments(
            current_keep_segments if current_keep_segments is not None else keep_segments,
            source_duration_sec=source_duration_sec,
            merge_gap_sec=0.0,
        ),
        source_duration_sec=source_duration_sec,
    )
    managed_ranges = sorted(
        _manual_editor_frontend_managed_auto_cut_ranges(
            analysis_payload,
            current_deleted_ranges=current_deleted_ranges if current_keep_segments is not None else None,
        ),
        key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)),
    )
    if not managed_ranges:
        return normalized_keep_segments
    resolved: list[dict[str, float]] = []
    for keep in normalized_keep_segments:
        keep_start = float(keep.get("start", 0.0) or 0.0)
        keep_end = float(keep.get("end", keep_start) or keep_start)
        if keep_end <= keep_start + 0.02:
            continue
        cursor = keep_start
        for managed in managed_ranges:
            managed_start = max(keep_start, float(managed.get("start", 0.0) or 0.0))
            managed_end = min(keep_end, float(managed.get("end", managed_start) or managed_start))
            if managed_end <= cursor + 0.001:
                continue
            if managed_start >= keep_end - 0.001:
                break
            if managed_start > cursor + 0.02:
                resolved.append({"start": round(cursor, 3), "end": round(managed_start, 3)})
            cursor = max(cursor, managed_end)
            if cursor >= keep_end - 0.02:
                break
        if cursor < keep_end - 0.02:
            resolved.append({"start": round(cursor, 3), "end": round(keep_end, 3)})
    return _normalize_manual_keep_segments(
        resolved,
        source_duration_sec=source_duration_sec,
        merge_gap_sec=0.0,
    )


def _manual_editor_draft_matches_base(
    payload: dict[str, Any] | None,
    *,
    editorial_timeline: Timeline,
    render_plan_timeline: Timeline | None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("base_timeline_id") or "") != str(editorial_timeline.id):
        return False
    if int(payload.get("base_timeline_version") or 0) != int(editorial_timeline.version or 1):
        return False
    expected_render_version = int(render_plan_timeline.version or 1) if render_plan_timeline is not None else None
    if expected_render_version is not None and int(payload.get("base_render_plan_version") or 0) != expected_render_version:
        return False
    return True


def _manual_editor_draft_timeline_rules_current(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        return int(payload.get("timeline_rules_version") or 0) == MANUAL_EDITOR_TIMELINE_RULES_VERSION
    except (TypeError, ValueError):
        return False


def _manual_editor_draft_subtitles_are_stale(
    *,
    draft_created_at: datetime | None,
    latest_subtitle_created_at: datetime | None,
) -> bool:
    if draft_created_at is None or latest_subtitle_created_at is None:
        return False
    return _coerce_utc_datetime(draft_created_at) < _coerce_utc_datetime(latest_subtitle_created_at)


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _manual_editor_latest_subtitle_created_at(session: AsyncSession, *, job_id: uuid.UUID) -> datetime | None:
    result = await session.execute(
        select(func.max(SubtitleItem.created_at)).where(
            SubtitleItem.job_id == job_id,
            SubtitleItem.version == 1,
        )
    )
    value = result.scalar_one_or_none()
    return value if isinstance(value, datetime) else None


async def _manual_editor_latest_subtitle_revision_created_at(session: AsyncSession, *, job_id: uuid.UUID) -> datetime | None:
    artifact_result = await session.execute(
        select(func.max(Artifact.created_at)).where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(
                [
                    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
                ]
            ),
        )
    )
    values = [
        value
        for value in (
            await _manual_editor_latest_subtitle_created_at(session, job_id=job_id),
            artifact_result.scalar_one_or_none(),
        )
        if isinstance(value, datetime)
    ]
    return max(values, key=_coerce_utc_datetime) if values else None


async def _load_manual_editor_aligned_source_subtitle_dicts(
    session: AsyncSession,
    *,
    job: Job,
    clean_text: bool = False,
    latest_projection_rows: list[dict[str, Any]] | None = None,
    latest_projection_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = _clean_manual_editor_subtitle_projection(
        await _load_manual_editor_source_subtitle_dicts(
            session,
            job_id=job.id,
            latest_projection_rows=latest_projection_rows,
            latest_projection_data=latest_projection_data,
        ),
        drop_empty=False,
        collapse_repeats=False,
        clean_text=clean_text,
    )
    raw_word_payloads = await _load_manual_editor_word_payloads(
        session,
        job_id=job.id,
        prefer_raw_text=True,
        normalize_to_text=False,
    )
    content_profile_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=_CONTENT_PROFILE_ARTIFACT_TYPES,
    )
    content_profile = _coerce_artifact_payload(content_profile_artifact)
    hotword_replacements = await _load_manual_editor_transcript_hotword_replacements(
        session,
        job=job,
        content_profile=content_profile,
    )
    context_text = _manual_editor_hotword_context_text(job, content_profile)
    rows = _manual_editor_align_source_rows_to_asr_words(
        rows,
        raw_word_payloads,
        context_text=context_text,
        hotword_replacements=hotword_replacements,
    )
    rows = _manual_editor_reveal_source_asr_words(
        rows,
        raw_word_payloads,
        context_text=context_text,
        hotword_replacements=hotword_replacements,
    )
    return _attach_manual_editor_words_to_subtitles(
        rows,
        await _load_manual_editor_word_payloads(session, job_id=job.id),
    )


def _manual_editor_subtitle_fingerprint(subtitles: list[dict[str, Any]]) -> str | None:
    return subtitle_payload_fingerprint(subtitles)


def _manual_editor_timeline_subtitle_fingerprint(payload: dict[str, Any] | None) -> str | None:
    data = payload if isinstance(payload, dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    manual_editor_meta = analysis.get("manual_editor") if isinstance(analysis.get("manual_editor"), dict) else {}
    for value in (
        manual_editor_meta.get("timeline_subtitle_fingerprint"),
        manual_editor_meta.get("source_subtitle_fingerprint"),
        manual_editor_meta.get("base_subtitle_fingerprint"),
        analysis.get("timeline_subtitle_fingerprint"),
        analysis.get("source_subtitle_fingerprint"),
        data.get("source_subtitle_fingerprint"),
        data.get("base_subtitle_fingerprint"),
    ):
        fingerprint = str(value or "").strip()
        if fingerprint:
            return fingerprint
    return None


def _manual_editor_timeline_subtitle_basis(payload: dict[str, Any] | None) -> str | None:
    data = payload if isinstance(payload, dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    manual_editor_meta = analysis.get("manual_editor") if isinstance(analysis.get("manual_editor"), dict) else {}
    for value in (
        manual_editor_meta.get("decision_subtitle_basis"),
        manual_editor_meta.get("source_subtitle_basis"),
        analysis.get("decision_subtitle_basis"),
        analysis.get("source_subtitle_basis"),
        data.get("decision_subtitle_basis"),
        data.get("source_subtitle_basis"),
    ):
        basis = str(value or "").strip()
        if basis:
            return basis
    return None


def _manual_editor_subtitle_basis_family(value: str | None) -> str:
    basis = str(value or "").strip().lower()
    if basis in {"canonical_transcript", "canonical_refresh"}:
        return "canonical"
    if basis in {"transcript_segment"}:
        return "transcript_segment"
    if basis in {"subtitle_item"}:
        return "subtitle_item"
    return basis


def _manual_editor_subtitle_basis(subtitles: list[dict[str, Any]]) -> str | None:
    sources = {
        str(item.get("projection_source") or "").strip()
        for item in subtitles
        if isinstance(item, dict)
    }
    for basis in ("canonical_transcript", "transcript_segment", "subtitle_item"):
        if basis in sources:
            return basis
    return None


def _manual_editor_timeline_matches_current_subtitles(
    payload: dict[str, Any] | None,
    *,
    current_subtitle_fingerprint: str | None,
    current_timeline_subtitle_fingerprint: str | None = None,
    current_subtitle_basis: str | None = None,
    current_timeline_subtitle_basis: str | None = None,
    timeline_created_at: datetime | None,
    latest_subtitle_revision_created_at: datetime | None,
) -> bool:
    timeline_fingerprint = _manual_editor_timeline_subtitle_fingerprint(payload)
    subtitles_are_stale = _manual_editor_draft_subtitles_are_stale(
        draft_created_at=timeline_created_at,
        latest_subtitle_created_at=latest_subtitle_revision_created_at,
    )
    timeline_is_newer_than_subtitles = False
    if timeline_created_at is not None and latest_subtitle_revision_created_at is not None:
        timeline_is_newer_than_subtitles = _coerce_utc_datetime(timeline_created_at) > _coerce_utc_datetime(
            latest_subtitle_revision_created_at
        )
    if timeline_fingerprint:
        current_fingerprints = {
            str(value or "").strip()
            for value in (current_subtitle_fingerprint, current_timeline_subtitle_fingerprint)
            if str(value or "").strip()
        }
        if timeline_fingerprint in current_fingerprints:
            return True
        timeline_basis = _manual_editor_timeline_subtitle_basis(payload)
        current_bases = {
            _manual_editor_subtitle_basis_family(value)
            for value in (current_subtitle_basis, current_timeline_subtitle_basis)
            if str(value or "").strip()
        }
        if (
            timeline_basis
            and _manual_editor_subtitle_basis_family(timeline_basis) in current_bases
            and not subtitles_are_stale
        ):
            return True
        if timeline_is_newer_than_subtitles:
            return True
        return False
    return not subtitles_are_stale


def _manual_editor_draft_subtitles_match_fingerprint(
    draft_payload: dict[str, Any] | None,
    current_subtitle_fingerprint: str | None,
) -> bool:
    if not draft_payload or not current_subtitle_fingerprint:
        return False
    draft_fingerprint = str(draft_payload.get("base_subtitle_fingerprint") or "").strip()
    return bool(draft_fingerprint and draft_fingerprint == current_subtitle_fingerprint)


def _manual_editor_request_subtitles_match_fingerprint(
    request: ManualEditorApplyIn,
    current_subtitle_fingerprint: str | None,
) -> bool:
    if not current_subtitle_fingerprint:
        return False
    request_fingerprint = str(request.base_subtitle_fingerprint or "").strip()
    return bool(request_fingerprint and request_fingerprint == current_subtitle_fingerprint)


def _validate_manual_editor_subtitle_revision(
    request: ManualEditorApplyIn,
    current_subtitle_fingerprint: str | None,
) -> None:
    request_fingerprint = str(request.base_subtitle_fingerprint or "").strip()
    if not request_fingerprint or not current_subtitle_fingerprint:
        return
    if request_fingerprint != current_subtitle_fingerprint:
        raise HTTPException(status_code=409, detail="字幕数据已更新，请刷新手动编辑器后再保存。")


def _manual_editor_stored_projection_matches_subtitles(
    subtitle_projection: dict[str, Any] | None,
    *,
    current_subtitle_fingerprint: str | None,
    projection_created_at: datetime | None,
    latest_subtitle_created_at: datetime | None,
) -> bool:
    if not subtitle_projection:
        return False
    projection_fingerprint = str(subtitle_projection.get("base_subtitle_fingerprint") or "").strip()
    if projection_fingerprint:
        return bool(current_subtitle_fingerprint and projection_fingerprint == current_subtitle_fingerprint)
    return not _manual_editor_draft_subtitles_are_stale(
        draft_created_at=projection_created_at,
        latest_subtitle_created_at=latest_subtitle_created_at,
    )


def _manual_video_transform_from_render_plan(
    render_plan: dict[str, Any] | None,
    *,
    render_plan_context: dict[str, Any] | None = None,
    video_transform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(video_transform, dict):
        payload = dict(video_transform)
    else:
        resolved_render_plan_context = (
            render_plan_context if isinstance(render_plan_context, dict) else _manual_editor_render_plan_context(render_plan)
        )
        payload = dict(resolved_render_plan_context.get("video_transform") or {})
    normalized = _manual_video_transform_payload(payload)
    normalized["rotation_manual"] = bool(payload.get("rotation_manual"))
    return normalized


def _manual_keep_segments_changed(
    previous_segments: list[dict[str, Any]],
    next_segments: list[dict[str, Any]],
    *,
    tolerance_sec: float = 0.02,
) -> bool:
    if len(previous_segments) != len(next_segments):
        return True
    for previous, next_item in zip(previous_segments, next_segments, strict=True):
        previous_start = float(previous.get("start", 0.0) or 0.0)
        previous_end = float(previous.get("end", 0.0) or 0.0)
        next_start = float(next_item.get("start", 0.0) or 0.0)
        next_end = float(next_item.get("end", 0.0) or 0.0)
        if abs(previous_start - next_start) > tolerance_sec or abs(previous_end - next_end) > tolerance_sec:
            return True
    return False


def _manual_editor_change_plan(
    *,
    previous_keep_segments: list[dict[str, Any]],
    next_keep_segments: list[dict[str, Any]],
    subtitle_overrides: list[dict[str, Any]],
    previous_video_transform: dict[str, Any] | None = None,
    next_video_transform: dict[str, Any] | None = None,
    previous_hyperframes_options: dict[str, Any] | None = None,
    next_hyperframes_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeline_changed = _manual_keep_segments_changed(previous_keep_segments, next_keep_segments)
    subtitle_changed = bool(subtitle_overrides)
    video_transform_changed = _manual_video_transform_payload(previous_video_transform) != _manual_video_transform_payload(next_video_transform)
    packaging_changed = normalize_hyperframes_options(previous_hyperframes_options) != normalize_hyperframes_options(next_hyperframes_options)
    rotation_changed = _manual_video_transform_payload(previous_video_transform).get("rotation_cw") != _manual_video_transform_payload(next_video_transform).get("rotation_cw")
    if timeline_changed:
        change_scope = "timeline"
        render_strategy = "full_timeline_render"
    elif video_transform_changed:
        change_scope = "video_transform"
        render_strategy = "source_orientation_render"
    elif subtitle_changed:
        change_scope = "subtitle_only"
        render_strategy = "reuse_timeline_effect_plan"
    elif packaging_changed:
        change_scope = "packaging"
        render_strategy = "packaging_only_render"
    else:
        change_scope = "no_material_change"
        render_strategy = "metadata_refresh_render"
    return {
        "change_scope": change_scope,
        "timeline_changed": timeline_changed,
        "subtitle_changed": subtitle_changed,
        "video_transform_changed": video_transform_changed,
        "packaging_changed": packaging_changed,
        "rotation_changed": rotation_changed,
        "render_strategy": render_strategy,
    }


def _manual_editor_change_contract(change_plan: dict[str, Any] | None) -> dict[str, Any]:
    return _shared_manual_editor_change_contract(change_plan)


def _manual_editor_rerun_issue_code(change_contract: dict[str, Any]) -> str:
    return _shared_manual_editor_rerun_issue_code(change_contract)


def _manual_editor_rerun_plan(change_contract: dict[str, Any] | None) -> dict[str, Any]:
    return _shared_manual_editor_rerun_plan(change_contract)


def _manual_editor_apply_detail(change_scope: str) -> str:
    return _shared_manual_editor_apply_detail(change_scope)


def _validate_manual_editor_base_revision(
    request: ManualEditorApplyIn,
    *,
    editorial_timeline: Timeline,
    render_plan_timeline: Timeline,
) -> None:
    requested_timeline_id = str(request.base_timeline_id or "").strip()
    if requested_timeline_id and requested_timeline_id != str(editorial_timeline.id):
        raise HTTPException(status_code=409, detail="手动编辑基于旧时间线，请刷新编辑器后再保存。")
    if request.base_timeline_version is not None and int(request.base_timeline_version) != int(editorial_timeline.version or 1):
        raise HTTPException(status_code=409, detail="手动编辑基于旧时间线版本，请刷新编辑器后再保存。")
    if request.base_render_plan_version is not None and int(request.base_render_plan_version) != int(render_plan_timeline.version or 1):
        raise HTTPException(status_code=409, detail="渲染计划已更新，请刷新编辑器后再保存。")


def _build_otio_style_manual_tracks(
    segments: list[dict[str, Any]],
    *,
    source_url: str,
    source_duration_sec: float,
    timebase: int = 24,
) -> dict[str, Any]:
    source_items: list[dict[str, Any]] = []
    output_items: list[dict[str, Any]] = []
    output_cursor = 0.0
    for index, segment in enumerate(segments):
        segment_type = str(segment.get("type") or "")
        start = round(max(0.0, float(segment.get("start", 0.0) or 0.0)), 3)
        end = round(max(start, float(segment.get("end", start) or start)), 3)
        duration = round(max(0.0, end - start), 3)
        if duration <= 0.0:
            continue
        source_range = {"start": start, "duration": duration}
        base_item: dict[str, Any] = {
            "id": f"{segment_type or 'segment'}_{index}",
            "type": "clip" if segment_type == "keep" else "gap",
            "name": f"{segment_type or 'segment'} {index + 1}",
            "source_range": source_range,
            "metadata": {
                "roughcut": {
                    "segment_type": segment_type,
                    "reason": str(segment.get("reason") or ""),
                }
            },
        }
        if segment_type == "keep":
            output_range = {"start": round(output_cursor, 3), "duration": duration}
            clip_item = {
                **base_item,
                "media_reference": {"target_url": source_url},
                "output_range": output_range,
            }
            source_items.append(clip_item)
            output_items.append(clip_item)
            output_cursor = round(output_cursor + duration, 3)
        else:
            source_items.append({**base_item, "output_range": None})

    return {
        "schema": "roughcut.editorial.v2",
        "timebase": int(timebase or 24),
        "source_duration_sec": round(max(0.0, float(source_duration_sec or 0.0)), 3),
        "output_duration_sec": round(output_cursor, 3),
        "tracks": [
            {
                "name": "source_video",
                "kind": "video",
                "items": source_items,
            },
            {
                "name": "output_video",
                "kind": "video",
                "items": output_items,
            },
        ],
    }


def _manual_subtitle_override_payloads(
    overrides: list[dict[str, Any]] | list[ManualEditorSubtitleOverrideIn],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for raw_item in overrides or []:
        if isinstance(raw_item, BaseModel):
            item = raw_item.model_dump()
        else:
            item = dict(raw_item or {})
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        payload: dict[str, Any] = {"index": index}
        if item.get("start_time") is not None:
            payload["start_time"] = round(max(0.0, float(item.get("start_time") or 0.0)), 3)
        if item.get("end_time") is not None:
            payload["end_time"] = round(max(0.0, float(item.get("end_time") or 0.0)), 3)
        if item.get("text_final") is not None:
            payload["text_final"] = str(item.get("text_final") or "").strip()
        if bool(item.get("delete", False)):
            payload["delete"] = True
        payloads.append(payload)
    payloads.sort(key=lambda item: int(item.get("index", 0) or 0))
    return payloads


def _manual_subtitle_replacement_payloads(
    replacements: list[dict[str, Any]] | list[ManualEditorSubtitleReplacementIn],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in replacements or []:
        if isinstance(raw_item, BaseModel):
            item = raw_item.model_dump()
        else:
            item = dict(raw_item or {})
        original = " ".join(str(item.get("original") or "").strip().split())[:80]
        replacement = " ".join(str(item.get("replacement") or "").strip().split())[:80]
        if not original or not replacement or original == replacement:
            continue
        key = (original, replacement)
        if key in seen:
            continue
        seen.add(key)
        try:
            occurrence_count = int(item.get("occurrence_count") or 1)
        except (TypeError, ValueError):
            occurrence_count = 1
        payloads.append(
            {
                "original": original,
                "replacement": replacement,
                "occurrence_count": max(1, min(999, occurrence_count)),
            }
        )
    return payloads


async def _record_manual_subtitle_replacement_memory(
    session: AsyncSession,
    *,
    job: Job,
    content_profile: dict[str, Any] | None,
    replacements: list[dict[str, Any]],
) -> None:
    if not replacements:
        return
    subject_domain = str((content_profile or {}).get("subject_domain") or job.workflow_template or "").strip()
    for item in replacements:
        original = str(item.get("original") or "").strip()
        replacement = str(item.get("replacement") or "").strip()
        if not original or not replacement or original == replacement:
            continue
        await upsert_learned_hotword(
            session,
            subject_domain=subject_domain,
            term=replacement,
            canonical_form=replacement,
            aliases=[original],
            source="manual_editor:subtitle_replacement",
            confidence=0.86,
            positive=True,
            metadata={
                "job_id": str(job.id),
                "source_name": str(job.source_name or ""),
                "original": original,
                "replacement": replacement,
                "occurrence_count": int(item.get("occurrence_count") or 1),
            },
        )


def _manual_video_transform_payload(transform: dict[str, Any] | ManualEditorVideoTransformIn | None) -> dict[str, Any]:
    if transform is None:
        return {"rotation_cw": 0}
    if isinstance(transform, BaseModel):
        payload = transform.model_dump()
    else:
        payload = dict(transform or {})
    try:
        raw_rotation = int(float(payload.get("rotation_cw") or 0))
    except (TypeError, ValueError):
        raw_rotation = 0
    normalized = raw_rotation % 360
    allowed = min((0, 90, 180, 270), key=lambda value: min(abs(value - normalized), 360 - abs(value - normalized)))
    aspect_ratio = str(payload.get("aspect_ratio") or "source").strip().lower()
    if aspect_ratio not in {"source", "16:9", "9:16", "1:1", "4:3"}:
        aspect_ratio = "source"
    resolution_mode = str(payload.get("resolution_mode") or "source").strip().lower()
    if resolution_mode not in {"source", "specified"}:
        resolution_mode = "source"
    resolution_preset = str(payload.get("resolution_preset") or "1080p").strip().lower()
    if resolution_preset not in {"1080p", "1440p", "2160p"}:
        resolution_preset = "1080p"
    return {
        "rotation_cw": int(allowed),
        "aspect_ratio": aspect_ratio,
        "resolution_mode": resolution_mode,
        "resolution_preset": resolution_preset,
    }


def _apply_manual_subtitle_overrides(
    subtitles: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | list[ManualEditorSubtitleOverrideIn],
    *,
    output_duration_sec: float,
    min_duration_sec: float = 0.08,
    min_gap_sec: float = 0.02,
) -> list[dict[str, Any]]:
    override_payloads = _manual_subtitle_override_payloads(overrides)
    if not override_payloads:
        return [dict(item) for item in subtitles]
    by_index = {int(item["index"]): item for item in override_payloads}
    output_upper_bound = max(0.0, float(output_duration_sec or 0.0))
    adjusted: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for fallback_index, subtitle in enumerate(subtitles):
        item = dict(subtitle)
        index = int(item.get("index", fallback_index) or fallback_index)
        seen_indexes.add(index)
        override = by_index.get(index)
        if override and bool(override.get("delete", False)):
            continue
        if override:
            start = float(item.get("start_time", 0.0) or 0.0)
            end = float(item.get("end_time", start) or start)
            if "start_time" in override:
                start = float(override["start_time"])
            if "end_time" in override:
                end = float(override["end_time"])
            start = max(0.0, min(start, output_upper_bound if output_upper_bound > 0.0 else start))
            end = max(start + min_duration_sec, end)
            if output_upper_bound > 0.0:
                end = min(end, output_upper_bound)
                start = min(start, max(0.0, end - min_duration_sec))
            item["start_time"] = round(start, 3)
            item["end_time"] = round(max(start + min_duration_sec, end), 3)
            if "text_final" in override:
                item["text_final"] = str(override.get("text_final") or "").strip()
        adjusted.append(item)

    for index, override in by_index.items():
        if index in seen_indexes or bool(override.get("delete", False)):
            continue
        start = max(0.0, float(override.get("start_time", 0.0) or 0.0))
        end = max(start + min_duration_sec, float(override.get("end_time", start + min_duration_sec) or start + min_duration_sec))
        if output_upper_bound > 0.0:
            end = min(end, output_upper_bound)
            start = min(start, max(0.0, end - min_duration_sec))
        text = str(override.get("text_final") or "").strip()
        adjusted.append(
            {
                "index": index,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "text_raw": text,
                "text_norm": text,
                "text_final": text,
            }
        )

    adjusted.sort(key=lambda item: (float(item.get("start_time", 0.0) or 0.0), int(item.get("index", 0) or 0)))
    previous_end = 0.0
    for item in adjusted:
        start = max(previous_end, float(item.get("start_time", 0.0) or 0.0))
        end = max(start + min_duration_sec, float(item.get("end_time", start) or start))
        if output_upper_bound > 0.0:
            end = min(end, output_upper_bound)
            start = min(start, max(0.0, end - min_duration_sec))
        item["start_time"] = round(start, 3)
        item["end_time"] = round(end, 3)
        previous_end = round(end + min_gap_sec, 3)
    return adjusted


def _resolve_manual_editor_source_path(job: Job) -> Path | None:
    direct_path = Path(str(job.source_path or "")).expanduser()
    if direct_path.exists() and direct_path.is_file():
        return direct_path
    resolve_path = getattr(get_storage(), "resolve_path", None)
    if callable(resolve_path):
        resolved = resolve_path(str(job.source_path or ""))
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _cached_local_file_stat(path: Path) -> tuple[int, int] | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return int(stat_result.st_size), int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))


def _file_response_cache_key(namespace: str, job_id: uuid.UUID | str, variant: str = "") -> str:
    suffix = f":{variant}" if variant else ""
    return f"{namespace}:{job_id}{suffix}"


def _get_cached_local_file(cache_key: str) -> Path | None:
    now = time.monotonic()
    with _FILE_RESPONSE_CACHE_LOCK:
        entry = _FILE_RESPONSE_CACHE.get(cache_key)
        if entry is None:
            return None
        expires_at, path_text, size_bytes, mtime_ns = entry
        if expires_at <= now:
            _FILE_RESPONSE_CACHE.pop(cache_key, None)
            return None

    path = Path(path_text)
    stat_result = _cached_local_file_stat(path)
    if stat_result != (size_bytes, mtime_ns):
        _invalidate_file_response_cache_key(cache_key)
        return None
    return path


def _set_cached_local_file(cache_key: str, path: Path) -> None:
    stat_result = _cached_local_file_stat(path)
    if stat_result is None:
        return
    size_bytes, mtime_ns = stat_result
    now = time.monotonic()
    with _FILE_RESPONSE_CACHE_LOCK:
        if len(_FILE_RESPONSE_CACHE) >= _FILE_RESPONSE_CACHE_MAX:
            expired_keys = [
                key for key, (expires_at, _, _, _) in _FILE_RESPONSE_CACHE.items() if expires_at <= now
            ]
            for key in expired_keys:
                _FILE_RESPONSE_CACHE.pop(key, None)
            while len(_FILE_RESPONSE_CACHE) >= _FILE_RESPONSE_CACHE_MAX:
                _FILE_RESPONSE_CACHE.pop(next(iter(_FILE_RESPONSE_CACHE)), None)
        _FILE_RESPONSE_CACHE[cache_key] = (
            now + _FILE_RESPONSE_CACHE_TTL_SEC,
            str(path),
            size_bytes,
            mtime_ns,
        )


def _invalidate_file_response_cache_key(cache_key: str) -> None:
    with _FILE_RESPONSE_CACHE_LOCK:
        _FILE_RESPONSE_CACHE.pop(cache_key, None)


def _invalidate_job_file_response_cache(job_id: uuid.UUID | str) -> None:
    source_prefix = _file_response_cache_key("source", job_id)
    download_prefix = _file_response_cache_key("download", job_id)
    with _FILE_RESPONSE_CACHE_LOCK:
        for key in list(_FILE_RESPONSE_CACHE):
            if key == source_prefix or key.startswith(f"{download_prefix}:"):
                _FILE_RESPONSE_CACHE.pop(key, None)


def _source_file_cache_get(job_id: uuid.UUID | str) -> Path | None:
    return _get_cached_local_file(_file_response_cache_key("source", job_id))


def _source_file_cache_set(job_id: uuid.UUID | str, path: Path) -> None:
    _set_cached_local_file(_file_response_cache_key("source", job_id), path)


def _download_file_cache_get(job_id: uuid.UUID | str, variant: str) -> Path | None:
    return _get_cached_local_file(_file_response_cache_key("download", job_id, variant))


def _download_file_cache_set(job_id: uuid.UUID | str, variant: str, path: Path) -> None:
    _set_cached_local_file(_file_response_cache_key("download", job_id, variant), path)


def _media_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".wav":
        return "audio/wav"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".srt", ".txt"}:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _inline_file_response(path: Path) -> FileResponse:
    return FileResponse(
        path=path,
        filename=path.name,
        media_type=_media_type_for_path(path),
        content_disposition_type="inline",
    )


async def _manual_editor_asset_dirs(session: AsyncSession, job: Job) -> list[Path]:
    artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=_DOWNSTREAM_PROFILE_ARTIFACT_TYPES,
    )
    profile = resolve_downstream_profile(artifact.data_json if artifact and isinstance(artifact.data_json, dict) else {})
    output_project_dir = get_output_project_dir(
        str(job.source_name or ""),
        job.created_at,
        content_profile=profile,
        output_dir=job.output_dir,
    )
    dirs = [manual_editor_asset_dir(job.id, output_project_dir=output_project_dir)]
    legacy_dir = manual_editor_asset_dir(job.id)
    if legacy_dir.resolve() != dirs[0].resolve():
        dirs.append(legacy_dir)
    return dirs


async def _manual_editor_primary_asset_dir(session: AsyncSession, job: Job) -> Path:
    return (await _manual_editor_asset_dirs(session, job))[0]


def _manual_editor_asset_path(job_id: uuid.UUID, filename: str, *, asset_dirs: list[Path] | None = None) -> Path | None:
    safe_name = Path(str(filename or "")).name
    if not safe_name:
        return None
    search_dirs = asset_dirs or [manual_editor_asset_dir(job_id)]
    for raw_asset_dir in search_dirs:
        asset_dir = raw_asset_dir.resolve()
        candidate = (asset_dir / safe_name).resolve()
        try:
            candidate.relative_to(asset_dir)
        except ValueError:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _manual_editor_preview_assets_response(
    job_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    ready: bool | None = None,
    warming: bool = False,
) -> ManualEditorPreviewAssetsOut:
    is_ready = bool(payload.get("ready", ready if ready is not None else True))
    video_ready = bool(payload.get("video_ready", is_ready))
    audio_ready = bool(payload.get("audio_ready", is_ready))
    thumbnail_urls = [
        f"/api/v1/jobs/{job_id}/manual-editor/assets/{Path(path).name}"
        for path in list(payload.get("thumbnail_paths") or [])
    ]
    thumbnail_items = [
        ManualEditorThumbnailOut(
            url=f"/api/v1/jobs/{job_id}/manual-editor/assets/{Path(str(item.get('path') or '')).name}",
            time_sec=round(float(item.get("time_sec") or 0.0), 3),
        )
        for item in list(payload.get("thumbnail_items") or [])
        if isinstance(item, dict) and Path(str(item.get("path") or "")).name
    ]
    silence_intervals = [
        normalized
        for item in list(payload.get("silence_intervals") or [])
        if isinstance(item, dict)
        if (normalized := _manual_editor_silence_payload(item)) is not None
    ]
    video_path = Path(str(payload.get("video_path") or ""))
    video_fallback_path = Path(str(payload.get("video_fallback_path") or ""))
    audio_path = Path(str(payload.get("audio_path") or ""))
    video_url = f"/api/v1/jobs/{job_id}/manual-editor/assets/{video_path.name}" if video_ready and video_path.name else None
    video_sources = []
    if video_url:
        video_sources.append(
            ManualEditorPreviewVideoSourceOut(
                url=video_url,
                type='video/mp4; codecs="avc1.42E01F, mp4a.40.2"',
            )
        )
    if payload.get("video_fallback_ready") and video_fallback_path.name:
        video_sources.append(
            ManualEditorPreviewVideoSourceOut(
                url=f"/api/v1/jobs/{job_id}/manual-editor/assets/{video_fallback_path.name}",
                type='video/webm; codecs="vp8, opus"',
            )
        )
    return ManualEditorPreviewAssetsOut(
        job_id=str(job_id),
        ready=is_ready,
        video_ready=video_ready,
        audio_ready=audio_ready,
        warming=bool(warming) and not is_ready,
        asset_version=int(payload.get("asset_version") or 0),
        status=str(payload.get("status") or ("ready" if is_ready else "missing")),
        stage=str(payload.get("stage") or ("ready" if is_ready else "not_started")),
        progress=float(payload.get("progress")) if payload.get("progress") is not None else (1.0 if is_ready else 0.0),
        video_url=video_url,
        video_sources=video_sources,
        audio_url=f"/api/v1/jobs/{job_id}/manual-editor/assets/{audio_path.name}" if audio_ready and audio_path.name else None,
        duration_sec=float(payload.get("duration_sec") or 0.0),
        sample_rate=int(payload.get("sample_rate") or 16000),
        peaks=[float(value) for value in list(payload.get("peaks") or [])],
        peak_count=int(payload.get("peak_count") or 0),
        silence_intervals=silence_intervals if is_ready else [],
        audio_peak=float(payload.get("audio_peak") or 0.0),
        audio_rms=float(payload.get("audio_rms") or 0.0),
        audio_lufs=float(payload.get("audio_lufs") or 0.0),
        audio_true_peak_db=float(payload.get("audio_true_peak_db") or 0.0),
        target_lufs=float(payload.get("target_lufs") or -16.0),
        auto_volume_gain=float(payload.get("auto_volume_gain") or 1.0),
        thumbnail_urls=thumbnail_urls if is_ready else [],
        thumbnail_items=thumbnail_items if is_ready else [],
        orientation_decision=(
            payload.get("orientation_decision")
            if isinstance(payload.get("orientation_decision"), dict)
            else {}
        ),
        cached=bool(payload.get("cached", False)),
        detail=str(payload.get("detail") or "") or None,
        error=str(payload.get("error") or "") or None,
        updated_at=str(payload.get("updated_at") or "") or None,
    )


def _manual_editor_orientation_decision_sync(source_path: Path) -> dict[str, Any]:
    from roughcut.media.rotation import detect_video_rotation_decision

    return asyncio.run(detect_video_rotation_decision(source_path)).to_dict()


async def _manual_editor_orientation_decision(source_path: Path) -> dict[str, Any]:
    return await asyncio.to_thread(_manual_editor_orientation_decision_sync, source_path)


def _warm_manual_editor_preview_assets(job_id: uuid.UUID, source_path: Path, duration_sec: float, asset_dir: Path) -> None:
    key = str(job_id)
    try:
        with _MANUAL_EDITOR_ASSET_WARMUP_SEMAPHORE:
            orientation_decision = _manual_editor_orientation_decision_sync(source_path)
            ensure_manual_editor_preview_assets(
                job_id=job_id,
                source_path=source_path,
                duration_sec=duration_sec,
                asset_dir=asset_dir,
                orientation_decision=orientation_decision,
            )
    except Exception:
        logger.exception("manual editor preview asset warmup failed job_id=%s", job_id)
    finally:
        with _MANUAL_EDITOR_ASSET_WARMUPS_LOCK:
            _MANUAL_EDITOR_ASSET_WARMUPS.discard(key)


def _manual_editor_asset_warmup_is_running(job_id: uuid.UUID) -> bool:
    with _MANUAL_EDITOR_ASSET_WARMUPS_LOCK:
        return str(job_id) in _MANUAL_EDITOR_ASSET_WARMUPS


def _queue_manual_editor_asset_warmup(
    job_id: uuid.UUID,
    source_path: Path,
    duration_sec: float,
    asset_dir: Path,
) -> bool:
    key = str(job_id)
    with _MANUAL_EDITOR_ASSET_WARMUPS_LOCK:
        if key in _MANUAL_EDITOR_ASSET_WARMUPS:
            return False
        _MANUAL_EDITOR_ASSET_WARMUPS.add(key)
    thread = threading.Thread(
        target=_warm_manual_editor_preview_assets,
        args=(job_id, source_path, duration_sec, asset_dir),
        name=f"manual-editor-warmup-{key[:8]}",
        daemon=True,
    )
    thread.start()
    return True


async def _load_latest_timeline_by_type(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    timeline_type: str,
) -> Timeline | None:
    result = await session.execute(
        select(Timeline)
        .where(Timeline.job_id == job_id, Timeline.timeline_type == timeline_type)
        .order_by(Timeline.version.desc(), Timeline.created_at.desc(), Timeline.id.desc())
    )
    return result.scalars().first()


def _manual_editor_is_synthetic_manual_timeline_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    segments = [segment for segment in list(payload.get("segments") or []) if isinstance(segment, dict)]
    if len(segments) < 2:
        return False
    reasons = {
        str(segment.get("reason") or "").strip()
        for segment in segments
    }
    return bool(reasons) and reasons.issubset(manual_editor_synthetic_timeline_reasons())


def _manual_editor_should_recover_previous_editorial_baseline(
    *,
    latest_editorial_payload: dict[str, Any] | None,
    cut_analysis_payload: dict[str, Any] | None,
    refine_plan_payload: dict[str, Any] | None,
) -> bool:
    if not _manual_editor_is_synthetic_manual_timeline_payload(latest_editorial_payload):
        return False
    if cut_analysis_accepted_cuts(cut_analysis_payload):
        return False
    if not cut_analysis_rule_candidates(cut_analysis_payload):
        return False
    if str((refine_plan_payload or {}).get("mode") or "").strip() != "manual_refine":
        return False
    return True


async def _load_manual_editor_recovered_baseline_timeline(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    latest_editorial_timeline: Timeline,
    cut_analysis_payload: dict[str, Any] | None,
    refine_plan_payload: dict[str, Any] | None,
) -> Timeline:
    latest_payload = latest_editorial_timeline.data_json if isinstance(latest_editorial_timeline.data_json, dict) else None
    if not _manual_editor_should_recover_previous_editorial_baseline(
        latest_editorial_payload=latest_payload,
        cut_analysis_payload=cut_analysis_payload,
        refine_plan_payload=refine_plan_payload,
    ):
        return latest_editorial_timeline
    result = await session.execute(
        select(Timeline)
        .where(
            Timeline.job_id == job_id,
            Timeline.timeline_type == "editorial",
            Timeline.id != latest_editorial_timeline.id,
        )
        .order_by(Timeline.version.desc(), Timeline.created_at.desc(), Timeline.id.desc())
    )
    for candidate in result.scalars():
        candidate_payload = candidate.data_json if isinstance(candidate.data_json, dict) else None
        if not _manual_editor_is_synthetic_manual_timeline_payload(candidate_payload):
            return candidate
    return latest_editorial_timeline


_MANUAL_EDITOR_REQUIRED_STEPS = tuple(
    step_name
    for step_name in PIPELINE_STEPS
    if (
        PIPELINE_STEPS.index(step_name) <= PIPELINE_STEPS.index("edit_plan")
        and step_name not in MANUAL_EDITOR_OPTIONAL_PREREQUISITE_STEPS
    )
)
_MANUAL_EDITOR_REQUIRED_OUTPUT_LABELS = {
    "source_media": "源视频",
    "media_meta": "媒体信息",
    "editorial_timeline": "剪辑时间线",
    "render_plan": "渲染计划",
}
_MANUAL_EDITOR_REQUIRED_OUTPUT_DETAILS = {
    "source_media": "源视频文件可用于浏览器预览。",
    "media_meta": "媒体时长和基础信息已写入。",
    "editorial_timeline": "剪辑时间线已写入数据库。",
    "render_plan": "渲染计划已写入数据库。",
}


def _manual_editor_missing_output_detail(missing: list[str]) -> str:
    labels = [
        _MANUAL_EDITOR_REQUIRED_OUTPUT_LABELS.get(item, item)
        for item in missing
    ]
    if not labels:
        return "正在生成手动调整所需信息。"
    return f"已完成上游步骤，仍在等待{'、'.join(labels)}写入完成。"


def _manual_editor_is_stop_after_cancelled_job(job: Job) -> bool:
    detail = str(job.error_message or "").strip()
    if "按 stop_after 主动停止" not in detail:
        return False
    return str(job.status or "").strip().lower() == "cancelled"


async def _build_manual_editor_readiness(
    *,
    job: Job,
    session: AsyncSession,
) -> ManualEditorReadinessOut:
    steps = _ordered_steps(list(job.steps or []))
    step_map = {step.step_name: step for step in steps}
    readiness_steps: list[ManualEditorReadinessStepOut] = []
    progress_units = 0.0
    current_step: str | None = None
    failed_step: JobStep | None = None

    for step_name in _MANUAL_EDITOR_REQUIRED_STEPS:
        step = step_map.get(step_name)
        status_value = str(step.status if step else "pending")
        metadata = dict(step.metadata_ or {}) if step is not None and isinstance(step.metadata_, dict) else {}
        progress_value = metadata.get("progress")
        progress = None
        if isinstance(progress_value, (int, float)):
            progress = max(0.0, min(1.0, float(progress_value)))
        if status_value in {"done", "skipped"}:
            progress_units += 1.0
        elif current_step is None:
            current_step = step_name
            if progress is not None:
                progress_units += progress
        elif progress is not None and status_value in {"running", "processing", "queued"}:
            progress_units += progress
        if status_value == "failed" and failed_step is None:
            failed_step = step
        readiness_steps.append(
            ManualEditorReadinessStepOut(
                step_name=step_name,
                label=STEP_LABELS.get(step_name, step_name),
                status=status_value,
                progress=progress,
                detail=str(metadata.get("detail") or "").strip() or None,
            )
        )

    missing: list[str] = []
    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    editorial_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
    render_plan_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
    if _resolve_manual_editor_source_path(job) is None:
        missing.append("source_media")
    if media_meta_artifact is None:
        missing.append("media_meta")
    if editorial_timeline is None:
        missing.append("editorial_timeline")
    if render_plan_timeline is None:
        missing.append("render_plan")

    output_statuses = [
        ("source_media", "source_media" not in missing),
        ("media_meta", "media_meta" not in missing),
        ("editorial_timeline", "editorial_timeline" not in missing),
        ("render_plan", "render_plan" not in missing),
    ]
    for output_name, is_ready in output_statuses:
        status_for_output = "done" if is_ready else "pending"
        if is_ready:
            progress_units += 1.0
        elif current_step is None:
            current_step = output_name
        readiness_steps.append(
            ManualEditorReadinessStepOut(
                step_name=output_name,
                label=_MANUAL_EDITOR_REQUIRED_OUTPUT_LABELS.get(output_name, output_name),
                status=status_for_output,
                progress=1.0 if is_ready else 0.0,
                detail=(
                    _MANUAL_EDITOR_REQUIRED_OUTPUT_DETAILS.get(output_name)
                    if is_ready
                    else f"正在等待{_MANUAL_EDITOR_REQUIRED_OUTPUT_LABELS.get(output_name, output_name)}生成完成。"
                ),
            )
        )

    readiness_unit_count = len(_MANUAL_EDITOR_REQUIRED_STEPS) + len(output_statuses)
    progress_percent = round((progress_units / max(1, readiness_unit_count)) * 100)
    status_value = str(job.status or "").strip().lower()
    prerequisite_detail = _manual_editor_prerequisite_detail(steps)
    can_open_editor = prerequisite_detail is None and not missing
    stop_after_cancelled_ready = can_open_editor and _manual_editor_is_stop_after_cancelled_job(job)
    can_edit = can_open_editor and status_value not in {"awaiting_init", "failed"} and (
        status_value != "cancelled" or stop_after_cancelled_ready
    )

    if stop_after_cancelled_ready:
        readiness_status: Literal["preprocessing", "ready", "failed", "blocked"] = "ready"
        detail = "手动调整所需信息已准备完成。"
        progress_percent = 100
        current_step = None
    elif failed_step is not None or status_value in {"failed", "cancelled"}:
        readiness_status: Literal["preprocessing", "ready", "failed", "blocked"] = "failed"
        failed_metadata = dict(failed_step.metadata_ or {}) if failed_step is not None else {}
        detail = str(
            (failed_step.error_message if failed_step is not None else None)
            or failed_metadata.get("detail")
            or job.error_message
            or "手动调整预处理失败。"
        ).strip()
    elif status_value == "awaiting_init":
        readiness_status = "blocked"
        detail = "当前任务尚未完成初始化，请先填写必要任务信息。"
    elif can_open_editor:
        readiness_status = "ready"
        detail = "手动调整所需信息已准备完成。"
        progress_percent = 100
        current_step = None
    else:
        readiness_status = "preprocessing"
        if missing and prerequisite_detail is None:
            detail = _manual_editor_missing_output_detail(missing)
        else:
            detail = prerequisite_detail or "正在生成手动调整所需信息。"

    return ManualEditorReadinessOut(
        job_id=str(job.id),
        status=readiness_status,
        can_open_editor=can_open_editor,
        can_edit=can_edit,
        progress_percent=max(0, min(100, int(progress_percent))),
        current_step=current_step,
        detail=detail or None,
        required_steps=readiness_steps,
        missing=missing,
    )


def _manual_editor_projection_baseline_rows(
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline = projected_subtitles or source_subtitles
    return _clean_manual_editor_subtitle_projection(
        baseline,
        drop_empty=False,
        collapse_repeats=False,
        clean_text=False,
    )


def _manual_editor_authoritative_projection_items(
    *,
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _manual_editor_projection_rows_are_output_timeline_rows(projected_subtitles):
        return _manual_editor_projection_baseline_rows(projected_subtitles, source_subtitles)
    return remap_subtitles_to_timeline(
        _manual_editor_projection_baseline_rows(projected_subtitles, source_subtitles),
        keep_segments,
    )


async def _build_manual_editor_session(
    *,
    job: Job,
    session: AsyncSession,
) -> ManualEditorSessionOut:
    editorial_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
    if editorial_timeline is None:
        raise HTTPException(status_code=404, detail="当前任务还没有可编辑时间线。")
    render_plan_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    refine_decision_plan_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=(ARTIFACT_TYPE_REFINE_DECISION_PLAN,),
    )
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    source_duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    editorial_payload = editorial_timeline.data_json if isinstance(editorial_timeline.data_json, dict) else None
    editorial_context = _manual_editor_editorial_context(editorial_payload)

    resolved_base_keep_segment_dicts = _manual_editor_base_keep_segment_dicts(
        editorial_payload,
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
    raw_base_keep_segments = [
        _manual_editor_segment_payload(segment, index=index)
        for index, segment in enumerate(resolved_base_keep_segment_dicts)
    ]
    if source_duration_sec <= 0.0:
        source_duration_sec = max((segment.end for segment in raw_base_keep_segments), default=0.0)

    subtitle_projection = editorial_context["subtitle_projection"]
    subtitle_overrides: list[dict[str, Any]] = []
    manual_projection_items: list[dict[str, Any]] = []
    render_plan_data = render_plan_timeline.data_json if render_plan_timeline and isinstance(render_plan_timeline.data_json, dict) else {}
    render_plan_context = _manual_editor_render_plan_context(render_plan_data)
    hyperframes_options = normalize_hyperframes_options(
        packaging_timeline_hyperframes_options(render_plan_context["packaging_timeline"])
    )
    base_video_transform = _manual_video_transform_from_render_plan(
        None,
        render_plan_context=render_plan_context,
    )
    video_transform = base_video_transform
    if isinstance(subtitle_projection, dict):
        subtitle_overrides = _manual_subtitle_override_payloads(
            [
                item
                for item in list(subtitle_projection.get("overrides") or [])
                if isinstance(item, dict)
            ]
        )
        manual_projection_items = [
            _manual_editor_sanitize_projection_item(item)
            for item in list(subtitle_projection.get("items") or [])
            if isinstance(item, dict)
        ]

    raw_subtitle_dicts, _projection_data = await _load_manual_editor_latest_subtitle_payloads(
        session,
        job_id=job.id,
        drop_empty=False,
        fallback_to_items=False,
    )
    _content_profile_artifact, content_profile = await _load_manual_editor_preferred_downstream_profile(
        session,
        job_id=job.id,
    )
    source_subtitle_dicts = await _load_manual_editor_aligned_source_subtitle_dicts(
        session,
        job=job,
        latest_projection_rows=raw_subtitle_dicts,
        latest_projection_data=_projection_data,
    )
    current_smart_cut_rules = _manual_editor_smart_cut_rules_payload(
        refine_decision_plan_artifact.data_json.get("smart_cut_rules")
        if refine_decision_plan_artifact
        and isinstance(refine_decision_plan_artifact.data_json, dict)
        else None
    )
    cut_analysis_payload = await _load_manual_editor_cut_analysis_payload(
        session,
        job=job,
        editorial_timeline_payload=None,
        editorial_analysis=editorial_context["editorial_analysis"],
        source_subtitles=source_subtitle_dicts,
        smart_cut_rules=current_smart_cut_rules,
        content_profile=content_profile,
    )
    baseline_editorial_timeline = await _load_manual_editor_recovered_baseline_timeline(
        session,
        job_id=job.id,
        latest_editorial_timeline=editorial_timeline,
        cut_analysis_payload=cut_analysis_payload,
        refine_plan_payload=(
            refine_decision_plan_artifact.data_json
            if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
            else None
        ),
    )
    baseline_editorial_payload = (
        baseline_editorial_timeline.data_json
        if isinstance(baseline_editorial_timeline.data_json, dict)
        else None
    )
    if baseline_editorial_timeline.id != editorial_timeline.id:
        baseline_editorial_context = _manual_editor_editorial_context(baseline_editorial_payload)
        resolved_base_keep_segment_dicts = _manual_editor_base_keep_segment_dicts(
            baseline_editorial_payload,
            refine_plan_payload=(
                refine_decision_plan_artifact.data_json
                if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
                else None
            ),
            editorial_timeline_id=str(baseline_editorial_timeline.id),
            editorial_timeline_version=int(baseline_editorial_timeline.version or 1),
            source_duration_sec=source_duration_sec,
            prefer_refine_plan=True,
        )
        raw_base_keep_segments = [
            _manual_editor_segment_payload(segment, index=index)
            for index, segment in enumerate(resolved_base_keep_segment_dicts)
        ]
        if source_duration_sec <= 0.0:
            source_duration_sec = max((segment.end for segment in raw_base_keep_segments), default=0.0)
        subtitle_projection = baseline_editorial_context["subtitle_projection"]
        subtitle_overrides = []
        manual_projection_items = []
        if isinstance(subtitle_projection, dict):
            subtitle_overrides = _manual_subtitle_override_payloads(
                [
                    item
                    for item in list(subtitle_projection.get("overrides") or [])
                    if isinstance(item, dict)
                ]
            )
            manual_projection_items = [
                _manual_editor_sanitize_projection_item(item)
                for item in list(subtitle_projection.get("items") or [])
                if isinstance(item, dict)
            ]
    multimodal_trim_review_payload = await _load_manual_editor_multimodal_trim_review_payload(
        session,
        job=job,
        cut_analysis_payload=cut_analysis_payload,
    )
    cut_analysis_payload = apply_multimodal_trim_review_to_cut_analysis(
        cut_analysis_payload,
        multimodal_trim_review_payload,
    )
    raw_silence_segments = cut_analysis_silence_segments(cut_analysis_payload)
    silence_segments = [
        normalized
        for item in raw_silence_segments
        if isinstance(item, dict)
        if (normalized := _manual_editor_silence_payload(item)) is not None
    ]
    rule_segments = _manual_editor_rule_segments(cut_analysis_payload)
    restored_base_keep_segment_dicts = _manual_editor_restore_frontend_managed_auto_cuts(
        raw_base_keep_segments,
        analysis_payload=cut_analysis_payload,
        source_duration_sec=source_duration_sec,
    )
    restored_base_keep_segments = [
        _manual_editor_segment_payload(segment, index=index)
        for index, segment in enumerate(restored_base_keep_segment_dicts)
    ]

    subtitle_fingerprint = _manual_editor_subtitle_fingerprint(source_subtitle_dicts)
    timeline_subtitle_fingerprint = _manual_editor_subtitle_fingerprint(raw_subtitle_dicts or source_subtitle_dicts)
    subtitle_basis = _manual_editor_subtitle_basis(source_subtitle_dicts)
    timeline_subtitle_basis = _manual_editor_subtitle_basis(raw_subtitle_dicts or source_subtitle_dicts)
    latest_subtitle_created_at = await _manual_editor_latest_subtitle_revision_created_at(session, job_id=job.id)
    if source_duration_sec <= 0.0:
        source_duration_sec = max(
            (
                float(item.get("end_time", item.get("end", 0.0)) or 0.0)
                for item in source_subtitle_dicts
                if isinstance(item, dict)
            ),
            default=0.0,
        )
    timeline_subtitles_current = _manual_editor_timeline_matches_current_subtitles(
        editorial_timeline.data_json if isinstance(editorial_timeline.data_json, dict) else None,
        current_subtitle_fingerprint=subtitle_fingerprint,
        current_timeline_subtitle_fingerprint=timeline_subtitle_fingerprint,
        current_subtitle_basis=subtitle_basis,
        current_timeline_subtitle_basis=timeline_subtitle_basis,
        timeline_created_at=editorial_timeline.created_at,
        latest_subtitle_revision_created_at=latest_subtitle_created_at,
    )
    if timeline_subtitles_current:
        base_keep_segments = restored_base_keep_segments
    elif source_duration_sec > 0.05:
        base_keep_segments = [
            _manual_editor_segment_payload({"start": 0.0, "end": source_duration_sec}, index=0)
        ]
    else:
        base_keep_segments = raw_base_keep_segments
    if not _manual_editor_stored_projection_matches_subtitles(
        subtitle_projection if isinstance(subtitle_projection, dict) else None,
        current_subtitle_fingerprint=subtitle_fingerprint,
        projection_created_at=baseline_editorial_timeline.created_at,
        latest_subtitle_created_at=latest_subtitle_created_at,
    ):
        subtitle_overrides = []
        manual_projection_items = []

    draft_saved_at: str | None = None
    draft_note: str | None = None
    smart_cut_rules = _manual_editor_smart_cut_rules_payload(
        refine_decision_plan_artifact.data_json.get("smart_cut_rules")
        if refine_decision_plan_artifact
        and isinstance(refine_decision_plan_artifact.data_json, dict)
        else None
    )
    base_video_summary = await _load_manual_editor_base_video_summary(session, job_id=job.id)
    video_summary = base_video_summary
    draft_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=(MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE,),
    )
    draft_payload = draft_artifact.data_json if draft_artifact and isinstance(draft_artifact.data_json, dict) else None
    keep_segments = base_keep_segments
    draft_subtitles_stale = _manual_editor_draft_subtitles_are_stale(
        draft_created_at=draft_artifact.created_at if draft_artifact is not None else None,
        latest_subtitle_created_at=latest_subtitle_created_at,
    )
    recovered_baseline_from_previous_editorial = baseline_editorial_timeline.id != editorial_timeline.id
    draft_active = (
        not recovered_baseline_from_previous_editorial
        and timeline_subtitles_current
        and _manual_editor_draft_matches_base(
        draft_payload,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        )
    )
    if draft_active and draft_payload is not None:
        raw_draft_keep_segments = [
            segment
            for segment in list(draft_payload.get("keep_segments") or [])
            if isinstance(segment, dict)
        ]
        draft_keep_segments: list[ManualEditorSegmentOut] = []
        if _manual_editor_draft_timeline_rules_current(draft_payload):
            try:
                normalized_draft_keep_segments = _normalize_manual_keep_segments(
                    raw_draft_keep_segments,
                    source_duration_sec=source_duration_sec,
                    merge_gap_sec=0.0,
                ) if raw_draft_keep_segments else []
                normalized_draft_keep_segments = _manual_editor_restore_frontend_managed_auto_cuts(
                    normalized_draft_keep_segments,
                    analysis_payload=cut_analysis_payload,
                    source_duration_sec=source_duration_sec,
                ) if normalized_draft_keep_segments else []
            except (HTTPException, TypeError, ValueError):
                normalized_draft_keep_segments = []
            draft_keep_segments = [
                _manual_editor_segment_payload(segment, index=index)
                for index, segment in enumerate(normalized_draft_keep_segments)
            ]
            if draft_keep_segments:
                keep_segments = draft_keep_segments
        draft_subtitles_match = _manual_editor_draft_subtitles_match_fingerprint(
            draft_payload,
            subtitle_fingerprint,
        )
        if draft_subtitles_match or (
            not draft_subtitles_stale
            and not str(draft_payload.get("base_subtitle_fingerprint") or "").strip()
        ):
            subtitle_overrides = _manual_subtitle_override_payloads(
                [
                    item
                    for item in list(draft_payload.get("subtitle_overrides") or [])
                    if isinstance(item, dict)
                ]
            )
        video_transform = _manual_video_transform_payload(draft_payload.get("video_transform"))
        smart_cut_rules = _manual_editor_smart_cut_rules_payload(draft_payload.get("smart_cut_rules")) or smart_cut_rules
        hyperframes_options = normalize_hyperframes_options(
            draft_payload.get("hyperframes_options")
            if isinstance(draft_payload.get("hyperframes_options"), dict)
            else hyperframes_options
        )
        video_summary = _normalize_manual_video_summary(draft_payload.get("video_summary")) or base_video_summary
        draft_saved_at = str(draft_payload.get("saved_at") or "") or None
        draft_note = str(draft_payload.get("note") or "") or None

    refine_decision_plan_payload = _manual_editor_refine_decision_plan_payload(
        refine_decision_plan_artifact.data_json
        if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
        else None,
        keep_segments=[segment.model_dump(include={"start", "end"}) for segment in keep_segments],
        source_duration_sec=source_duration_sec,
        subtitle_fingerprint=subtitle_fingerprint,
        render_plan_version=int(render_plan_timeline.version) if render_plan_timeline is not None else None,
        cut_analysis=cut_analysis_payload,
        audio_defaults={
            **dict(render_plan_context.get("loudness") or {}),
            **dict(render_plan_context.get("voice_processing") or {}),
        },
        video_transform=video_transform,
        smart_cut_rules=smart_cut_rules,
        mode="manual_refine" if draft_active else "auto_refine",
        note=draft_note,
        editorial_timeline_id=str(editorial_timeline.id),
        editorial_timeline_version=int(editorial_timeline.version or 1),
    )

    manual_projection_suspicious = _manual_editor_projection_has_suspicious_subtitle_timing(
        manual_projection_items,
        split_profile={},
    )
    projection_contract_locked = _manual_editor_projection_contract_locked(
        manual_projection_items=manual_projection_items,
        raw_projection_rows=raw_subtitle_dicts,
        projection_data=_projection_data,
        draft_active=draft_active,
        manual_projection_suspicious=manual_projection_suspicious,
    )
    keep_segment_payloads = [segment.model_dump(include={"start", "end"}) for segment in keep_segments]
    source_projection_items = _manual_editor_source_fallback_projection_items(
        source_subtitle_dicts,
        keep_segment_payloads,
    )
    display_projection_basis = "source_timeline_projection"
    if manual_projection_items and not draft_active and not manual_projection_suspicious:
        projected_subtitles = manual_projection_items
        display_projection_basis = "manual_projection_override"
    else:
        projected_subtitles = list(source_projection_items)
        if subtitle_overrides:
            base_output_duration_sec = max((float(item.get("end_time", 0.0) or 0.0) for item in projected_subtitles), default=0.0)
            projected_subtitles = _apply_manual_subtitle_overrides(
                projected_subtitles,
                subtitle_overrides,
                output_duration_sec=base_output_duration_sec,
            )
    projected_subtitles = _clean_manual_editor_subtitle_projection(
        projected_subtitles,
        clean_text=False,
        collapse_repeats=False,
    )
    projected_subtitles = _clean_manual_editor_subtitle_projection(
        projected_subtitles,
        clean_text=False,
        collapse_repeats=False,
    )
    projection_validation = validate_projected_subtitles_against_source(
        projected_subtitles,
        source_subtitles=source_subtitle_dicts,
        keep_segments=[segment.model_dump(include={"start", "end"}) for segment in keep_segments],
        fallback_source_subtitles=None,
        apply_annotation_repair=False,
    )
    validated_projected_subtitles = list(projection_validation.subtitles)
    projected_subtitles = _clean_manual_editor_subtitle_projection(
        projected_subtitles,
        clean_text=False,
    )
    projection_diagnostics = {
        "projection_refresh_required": False,
        "rebuilt_from_canonical_fallback": False,
        "manual_projection_suspicious": bool(manual_projection_suspicious),
        "source_projection_fallback_applied": False,
        "source_projection_fallback_reason": None,
        "display_projection_basis": display_projection_basis,
        "projection_validation_fallback_used": bool(getattr(projection_validation, "fallback_used", False)),
        "projection_validation_mismatch_detected": bool(getattr(projection_validation, "mismatch_detected", False)),
        "validated_projection_count": len(validated_projected_subtitles),
        "display_projection_count": len(projected_subtitles),
        "source_fallback_projection_count": len(source_projection_items),
        "source_row_split_diagnostics": _manual_editor_source_row_split_diagnostics(source_subtitle_dicts),
        "projection_validation": (
            projection_validation.model_dump()
            if hasattr(projection_validation, "model_dump")
            else dict(projection_validation or {})
            if isinstance(projection_validation, dict)
            else None
        ),
    }
    projection_fallback_reasons = projection_output_fallback_reasons(
        projection_diagnostics,
        include_refresh_required=True,
    )
    status_detail = _manual_editor_detail_for_job_status(str(job.status or ""))
    prerequisite_detail = _manual_editor_prerequisite_detail(list(job.steps or []))
    session_detail = status_detail or prerequisite_detail
    if projection_fallback_reasons:
        projection_contract_locked = True
        fallback_detail = (
            "字幕投影仍处于 fallback/待刷新状态，不能作为正式可编辑基线："
            + ", ".join(projection_fallback_reasons)
        )
        session_detail = fallback_detail if session_detail is None else f"{session_detail}；{fallback_detail}"
    source_path = _resolve_manual_editor_source_path(job)
    return ManualEditorSessionOut(
        job_id=str(job.id),
        timeline_id=str(editorial_timeline.id),
        timeline_version=int(editorial_timeline.version or 1),
        render_plan_version=int(render_plan_timeline.version) if render_plan_timeline is not None else None,
        subtitle_fingerprint=subtitle_fingerprint,
        source_name=str(job.source_name or ""),
        source_duration_sec=round(max(0.0, source_duration_sec), 3),
        source_url=f"/api/v1/jobs/{job.id}/source/file" if source_path is not None else None,
        video_summary=video_summary,
        base_video_summary=base_video_summary,
        keep_segments=keep_segments,
        base_keep_segments=base_keep_segments,
        silence_segments=silence_segments,
        rule_segments=rule_segments,
        cut_analysis=cut_analysis_payload,
        refine_decision_plan=refine_decision_plan_payload,
        multimodal_trim_review=multimodal_trim_review_payload,
        strategy_review_context=(
            dict(render_plan_context.get("strategy_review_context") or {})
            if isinstance(render_plan_context.get("strategy_review_context"), dict)
            else dict(content_profile.get("strategy_review_context") or {})
            if isinstance(content_profile.get("strategy_review_context"), dict)
            else None
        ),
        source_subtitle_basis=subtitle_basis,
        projected_subtitle_basis=_manual_editor_subtitle_basis(projected_subtitles),
        projection_contract_locked=projection_contract_locked,
        projection_diagnostics=projection_diagnostics,
        source_subtitles=[
            _manual_editor_subtitle_payload(item, index=index)
            for index, item in enumerate(source_subtitle_dicts)
        ],
        projected_subtitles=[
            _manual_editor_subtitle_payload(item, index=index)
            for index, item in enumerate(projected_subtitles)
        ],
        subtitle_overrides=[ManualEditorSubtitleOverrideIn(**item) for item in subtitle_overrides],
        video_transform=ManualEditorVideoTransformIn(**video_transform),
        base_video_transform=ManualEditorVideoTransformIn(**base_video_transform),
        smart_cut_rules=smart_cut_rules,
        hyperframes_options=hyperframes_options,
        draft_saved_at=draft_saved_at,
        draft_note=draft_note,
        editable=session_detail is None,
        detail=session_detail,
    )


@router.get("/{job_id}/source/file")
async def get_source_file(job_id: uuid.UUID):
    cached_path = _source_file_cache_get(job_id)
    if cached_path is not None:
        return _inline_file_response(cached_path)

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        source_path = _resolve_manual_editor_source_path(job)
        if source_path is None:
            raise HTTPException(status_code=404, detail="Source media is not available locally for preview")
    _source_file_cache_set(job_id, source_path)
    return _inline_file_response(source_path)


@router.get("/{job_id}/manual-editor/assets", response_model=ManualEditorPreviewAssetsOut)
async def get_manual_editor_preview_assets(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    source_path = _resolve_manual_editor_source_path(job)
    if source_path is None:
        raise HTTPException(status_code=404, detail="Source media is not available locally for preview assets")
    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    asset_dir = await _manual_editor_primary_asset_dir(session, job)
    orientation_decision = await _manual_editor_orientation_decision(source_path)
    payload = await asyncio.to_thread(
        ensure_manual_editor_preview_assets,
        job_id=job.id,
        source_path=source_path,
        duration_sec=duration_sec,
        asset_dir=asset_dir,
        orientation_decision=orientation_decision,
    )
    return _manual_editor_preview_assets_response(job.id, payload, ready=True)


@router.get("/{job_id}/manual-editor/assets/status", response_model=ManualEditorPreviewAssetsOut)
async def get_manual_editor_preview_assets_status(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    source_path = _resolve_manual_editor_source_path(job)
    if source_path is None:
        raise HTTPException(status_code=404, detail="Source media is not available locally for preview assets")
    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    asset_dir = await _manual_editor_primary_asset_dir(session, job)
    payload = load_manual_editor_preview_assets(
        job_id=job.id,
        source_path=source_path,
        duration_sec=duration_sec,
        asset_dir=asset_dir,
    )
    return _manual_editor_preview_assets_response(
        job.id,
        payload,
        ready=bool(payload.get("ready", False)),
        warming=_manual_editor_asset_warmup_is_running(job.id),
    )


@router.post("/{job_id}/manual-editor/assets/warm", response_model=ManualEditorPreviewAssetsOut)
async def warm_manual_editor_preview_assets(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    source_path = _resolve_manual_editor_source_path(job)
    if source_path is None:
        raise HTTPException(status_code=404, detail="Source media is not available locally for preview assets")
    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    asset_dir = await _manual_editor_primary_asset_dir(session, job)
    payload = load_manual_editor_preview_assets(job_id=job.id, source_path=source_path, duration_sec=duration_sec, asset_dir=asset_dir)
    if (
        not payload.get("ready")
        and str(payload.get("status") or "") != "failed"
        and not _manual_editor_asset_warmup_is_running(job.id)
    ):
        payload = {**payload, **mark_manual_editor_preview_assets_queued(job.id, asset_dir=asset_dir)}
        _queue_manual_editor_asset_warmup(job.id, source_path, duration_sec, asset_dir)
    return _manual_editor_preview_assets_response(
        job.id,
        payload,
        ready=bool(payload.get("ready", False)),
        warming=not bool(payload.get("ready", False)) and str(payload.get("status") or "") != "failed",
    )


@router.get("/{job_id}/manual-editor/assets/{filename}")
async def get_manual_editor_asset_file(job_id: uuid.UUID, filename: str, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    path = _manual_editor_asset_path(job_id, filename, asset_dirs=await _manual_editor_asset_dirs(session, job))
    if path is None:
        raise HTTPException(status_code=404, detail="Manual editor asset not found")
    return _inline_file_response(path)


@router.get("/{job_id}/manual-editor/readiness", response_model=ManualEditorReadinessOut)
async def get_manual_editor_readiness(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _build_manual_editor_readiness(job=job, session=session)


@router.get("/{job_id}/manual-editor", response_model=ManualEditorSessionOut)
async def get_manual_editor_session(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    manual_editor_session = await _build_manual_editor_session(job=job, session=session)
    if bool(session.info.pop("manual_editor_projection_cache_refreshed", False)):
        await session.commit()
    return manual_editor_session


@router.post("/{job_id}/manual-editor/draft", response_model=ManualEditorDraftOut)
async def save_manual_editor_draft(
    job_id: uuid.UUID,
    request: ManualEditorApplyIn,
    session: AsyncSession = Depends(get_session),
):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    blocked_detail = _manual_editor_detail_for_job_status(str(job.status or "")) or _manual_editor_prerequisite_detail(list(job.steps or []))
    if blocked_detail:
        raise HTTPException(status_code=409, detail=blocked_detail)

    editorial_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
    render_plan_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
    if editorial_timeline is None or render_plan_timeline is None:
        raise HTTPException(status_code=404, detail="当前任务缺少可保存的时间线数据。")
    _validate_manual_editor_base_revision(
        request,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
    )

    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    source_duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    editorial_payload = editorial_timeline.data_json if isinstance(editorial_timeline.data_json, dict) else {}
    editorial_context = _manual_editor_editorial_context(editorial_payload)
    if source_duration_sec <= 0.0:
        source_duration_sec = max(
            (
                float(segment.get("end", 0.0) or 0.0)
                for segment in list(editorial_context.get("raw_keep_segments") or [])
            ),
            default=0.0,
        )
    keep_segments = _normalize_manual_keep_segments(
        request.keep_segments,
        source_duration_sec=source_duration_sec,
        merge_gap_sec=0.0,
    )
    current_source_subtitles = await _load_manual_editor_aligned_source_subtitle_dicts(session, job=job)
    _content_profile_artifact, content_profile = await _load_manual_editor_preferred_downstream_profile(
        session,
        job_id=job.id,
    )
    subtitle_fingerprint = _manual_editor_subtitle_fingerprint(current_source_subtitles)
    _validate_manual_editor_subtitle_revision(request, subtitle_fingerprint)
    request_subtitles_match = _manual_editor_request_subtitles_match_fingerprint(request, subtitle_fingerprint)
    subtitle_override_payloads = (
        _manual_subtitle_override_payloads(request.subtitle_overrides)
        if request_subtitles_match
        else []
    )
    subtitle_replacement_payloads = (
        _manual_subtitle_replacement_payloads(request.subtitle_replacements)
        if request_subtitles_match
        else []
    )
    video_transform = _manual_video_transform_payload(request.video_transform)
    smart_cut_rules = _manual_editor_smart_cut_rules_payload(request.smart_cut_rules)
    render_plan_context = _manual_editor_render_plan_context(
        render_plan_timeline.data_json if isinstance(render_plan_timeline.data_json, dict) else {}
    )
    base_hyperframes_options = normalize_hyperframes_options(
        packaging_timeline_hyperframes_options(render_plan_context["packaging_timeline"])
    )
    hyperframes_options = (
        normalize_hyperframes_options(request.hyperframes_options)
        if isinstance(request.hyperframes_options, dict)
        else base_hyperframes_options
    )
    video_summary = _normalize_manual_video_summary(request.video_summary)
    saved_at = datetime.now(timezone.utc).isoformat()
    await _persist_manual_video_summary_evidence(
        session,
        job=job,
        video_summary=video_summary,
        updated_at=saved_at,
    )
    await _persist_manual_video_summary_source_context(
        session,
        job_id=job.id,
        video_summary=video_summary,
        updated_at=saved_at,
    )
    await session.execute(
        delete(Artifact).where(
            Artifact.job_id == job.id,
            Artifact.artifact_type == MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE,
            data_json={
                "schema": MANUAL_EDITOR_DRAFT_SCHEMA,
                "timeline_rules_version": MANUAL_EDITOR_TIMELINE_RULES_VERSION,
                "saved_at": saved_at,
                "base_timeline_id": str(editorial_timeline.id),
                "base_timeline_version": int(editorial_timeline.version or 1),
                "base_render_plan_version": int(render_plan_timeline.version or 1),
                "base_subtitle_fingerprint": subtitle_fingerprint,
                "keep_segments": keep_segments,
                "subtitle_overrides": subtitle_override_payloads,
                "subtitle_replacements": subtitle_replacement_payloads,
                "video_transform": video_transform,
                "smart_cut_rules": smart_cut_rules,
                "hyperframes_options": hyperframes_options,
                "video_summary": video_summary,
                "note": str(request.note or "").strip() or None,
            },
        )
    )
    current_cut_analysis_payload = await _load_manual_editor_cut_analysis_payload(
        session,
        job=job,
        editorial_timeline_payload=None,
        editorial_analysis=editorial_context["editorial_analysis"],
        source_subtitles=current_source_subtitles,
        smart_cut_rules=smart_cut_rules,
        content_profile=content_profile,
    )
    reviewed_multimodal_trim_review_payload = await review_multimodal_trim_review_payload(
        _manual_editor_multimodal_trim_review_payload(
            cut_analysis_payload=current_cut_analysis_payload,
            source_name=str(job.source_name or ""),
            job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
        ),
        source_path=_resolve_manual_editor_source_path(job),
        source_meta=_manual_editor_multimodal_review_source_meta(job=job, content_profile=content_profile),
    )
    current_cut_analysis_payload = apply_multimodal_trim_review_to_cut_analysis(
        current_cut_analysis_payload,
        reviewed_multimodal_trim_review_payload,
    )
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_CUT_ANALYSIS,
            data_json=current_cut_analysis_payload,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,
            data_json=reviewed_multimodal_trim_review_payload,
        )
    )
    render_plan_data = render_plan_timeline.data_json if isinstance(render_plan_timeline.data_json, dict) else {}
    render_plan_context = _manual_editor_render_plan_context(render_plan_data)
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_REFINE_DECISION_PLAN,
            data_json=_manual_editor_build_refine_decision_plan_from_render_plan(
                keep_segments=keep_segments,
                source_duration_sec=source_duration_sec,
                mode="manual_refine",
                subtitle_fingerprint=subtitle_fingerprint,
                render_plan_data=None,
                render_plan_version=int(render_plan_timeline.version or 1) if render_plan_timeline is not None else None,
                cut_analysis=current_cut_analysis_payload,
                audio_defaults={
                    **dict(render_plan_context.get("loudness") or {}),
                    **dict(render_plan_context.get("voice_processing") or {}),
                },
                video_transform=video_transform,
                smart_cut_rules=smart_cut_rules,
                note=str(request.note or "").strip() or None,
                editorial_timeline_id=str(editorial_timeline.id),
                editorial_timeline_version=int(editorial_timeline.version or 1),
            ),
        )
    )
    await session.commit()
    return ManualEditorDraftOut(
        job_id=str(job.id),
        saved_at=saved_at,
        keep_segment_count=len(keep_segments),
        subtitle_override_count=len(subtitle_override_payloads),
        detail=(
            "手动调整草稿已自动保存；字幕已重建，旧页面里的字幕修改已忽略，请刷新后再改字幕。"
            if not request_subtitles_match and (request.subtitle_overrides or request.subtitle_replacements)
            else "手动调整草稿已自动保存。"
        ),
    )


@router.post("/{job_id}/manual-editor/rotation/detect", response_model=ManualEditorRotationDetectOut)
async def detect_manual_editor_rotation(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    from roughcut.media.rotation import detect_video_rotation

    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    source_path = _resolve_manual_editor_source_path(job)
    if source_path is None:
        raise HTTPException(status_code=404, detail="Source media is not available locally for rotation detection")
    rotation_cw = await detect_video_rotation(source_path)
    return ManualEditorRotationDetectOut(
        job_id=str(job.id),
        rotation_cw=int(rotation_cw),
        detail=f"自动检测建议顺时针旋转 {int(rotation_cw)}°。",
    )


@router.post("/{job_id}/manual-editor/apply", response_model=ManualEditorApplyOut)
async def apply_manual_editor_timeline(
    job_id: uuid.UUID,
    request: ManualEditorApplyIn,
    session: AsyncSession = Depends(get_session),
):
    from roughcut.pipeline.steps import (
        _job_creative_profile,
        _plan_insert_asset_slot,
        _plan_music_entry,
    )

    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    blocked_detail = _manual_editor_detail_for_job_status(str(job.status or "")) or _manual_editor_apply_conflict_detail(list(job.steps or []))
    if blocked_detail:
        raise HTTPException(status_code=409, detail=blocked_detail)

    editorial_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
    render_plan_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
    if editorial_timeline is None or render_plan_timeline is None:
        raise HTTPException(status_code=404, detail="当前任务缺少可重建的时间线数据。")
    _validate_manual_editor_base_revision(
        request,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
    )

    media_meta_artifact = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
    media_meta = media_meta_artifact.data_json if media_meta_artifact and isinstance(media_meta_artifact.data_json, dict) else {}
    source_duration_sec = float(media_meta.get("duration_sec") or media_meta.get("duration") or 0.0)
    previous_editorial_payload = editorial_timeline.data_json if isinstance(editorial_timeline.data_json, dict) else {}
    previous_editorial_context = _manual_editor_editorial_context(previous_editorial_payload)
    previous_editorial_analysis = previous_editorial_context["editorial_analysis"]
    raw_previous_keep_segments = list(previous_editorial_context.get("raw_keep_segments") or [])
    if source_duration_sec <= 0.0:
        source_duration_sec = max(
            (
                float(segment.get("end", 0.0) or 0.0)
                for segment in raw_previous_keep_segments
            ),
            default=0.0,
        )

    source_subtitle_dicts = await _load_manual_editor_aligned_source_subtitle_dicts(session, job=job)
    subtitle_fingerprint = _manual_editor_subtitle_fingerprint(source_subtitle_dicts)
    _validate_manual_editor_subtitle_revision(request, subtitle_fingerprint)
    subtitle_override_payloads = _manual_subtitle_override_payloads(request.subtitle_overrides)
    subtitle_replacement_payloads = _manual_subtitle_replacement_payloads(request.subtitle_replacements)
    video_transform = _manual_video_transform_payload(request.video_transform)
    smart_cut_rules = _manual_editor_smart_cut_rules_payload(request.smart_cut_rules)
    requested_hyperframes_options = (
        normalize_hyperframes_options(request.hyperframes_options)
        if isinstance(request.hyperframes_options, dict)
        else None
    )
    video_summary = _normalize_manual_video_summary(request.video_summary)
    _profile_artifact, content_profile = await _load_manual_editor_preferred_downstream_profile(
        session,
        job_id=job.id,
    )
    baseline_cut_analysis_payload = await _load_manual_editor_cut_analysis_payload(
        session,
        job=job,
        editorial_timeline_payload=None,
        editorial_analysis=previous_editorial_analysis,
        source_subtitles=source_subtitle_dicts,
        smart_cut_rules=smart_cut_rules,
        content_profile=content_profile,
    )
    previous_keep_segments = _manual_editor_restore_frontend_managed_auto_cuts(
        raw_previous_keep_segments,
        analysis_payload=baseline_cut_analysis_payload,
        source_duration_sec=source_duration_sec,
    )
    requested_keep_segments = _normalize_manual_keep_segments(
        request.keep_segments,
        source_duration_sec=source_duration_sec,
        merge_gap_sec=0.0,
    )
    effective_keep_segments = _manual_editor_apply_frontend_managed_auto_cuts(
        requested_keep_segments,
        analysis_payload=baseline_cut_analysis_payload,
        source_duration_sec=source_duration_sec,
        current_keep_segments=raw_previous_keep_segments,
    )
    # Apply workflow始终以对齐后的源字幕轨作为可编辑基准，避免在应用阶段再次进行可变的投影来源切换。
    remapped_subtitles = _manual_editor_source_fallback_projection_items(
        source_subtitle_dicts,
        effective_keep_segments,
    )
    projection_validation = validate_projected_subtitles_against_source(
        remapped_subtitles,
        source_subtitles=source_subtitle_dicts,
        keep_segments=effective_keep_segments,
        fallback_source_subtitles=None,
        apply_annotation_repair=False,
    )
    if bool(getattr(projection_validation, "mismatch_detected", False)):
        logger.debug(
            "manual_editor_apply_projection_validation_mismatch job_id=%s mismatch=%s fallback_used=%s",
            str(job.id),
            bool(getattr(projection_validation, "mismatch_detected", False)),
            bool(getattr(projection_validation, "fallback_used", False)),
        )
    subtitle_projection_repair = {
        "repair_requested": False,
        "repair_applied": False,
        "mismatch_detected": bool(getattr(projection_validation, "mismatch_detected", False)),
        "fallback_used": bool(getattr(projection_validation, "fallback_used", False)),
        "changed": bool(getattr(projection_validation, "changed", False)),
        "input_count": int(getattr(projection_validation, "input_count", 0) or 0),
        "output_count": int(getattr(projection_validation, "output_count", 0) or 0),
        "repair_mode": None,
        "source": "manual_editor_apply_source_baseline",
    }
    base_output_duration_sec = max((float(item.get("end_time", 0.0) or 0.0) for item in remapped_subtitles), default=0.0)
    previous_render_plan = dict(render_plan_timeline.data_json or {})
    remapped_subtitles = _apply_manual_subtitle_overrides(
        remapped_subtitles,
        subtitle_override_payloads,
        output_duration_sec=base_output_duration_sec,
    )
    remapped_subtitles = _clean_manual_editor_subtitle_projection(
        remapped_subtitles,
        clean_text=False,
    )
    previous_render_plan_context = _manual_editor_render_plan_context(previous_render_plan)
    previous_packaging_timeline = previous_render_plan_context["packaging_timeline"]
    previous_hyperframes_options = normalize_hyperframes_options(
        packaging_timeline_hyperframes_options(previous_packaging_timeline)
    )
    effective_hyperframes_options = (
        requested_hyperframes_options
        if requested_hyperframes_options is not None
        else previous_hyperframes_options
    )
    previous_video_transform = _manual_video_transform_from_render_plan(
        None,
        render_plan_context=previous_render_plan_context,
    )
    change_plan = _manual_editor_change_plan(
        previous_keep_segments=previous_keep_segments,
        next_keep_segments=requested_keep_segments,
        subtitle_overrides=subtitle_override_payloads,
        previous_video_transform=previous_video_transform,
        next_video_transform=video_transform,
        previous_hyperframes_options=previous_hyperframes_options,
        next_hyperframes_options=effective_hyperframes_options,
    )
    change_contract = _manual_editor_change_contract(change_plan)
    await _record_manual_subtitle_replacement_memory(
        session,
        job=job,
        content_profile=content_profile,
        replacements=subtitle_replacement_payloads,
    )
    if video_summary:
        content_profile = _apply_manual_video_summary_to_profile(
            content_profile,
            video_summary=video_summary,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    editing_skill = packaging_timeline_editing_skill(previous_packaging_timeline)
    previous_chapter_analysis = packaging_timeline_chapter_analysis(previous_packaging_timeline)
    previous_editing_accents = packaging_timeline_editing_accents(previous_packaging_timeline)
    previous_subtitles = packaging_timeline_subtitles(previous_packaging_timeline)
    previous_smart_effect_style = str(previous_editing_accents.get("style") or "smart_effect_commercial")
    output_duration_sec = max((float(item.get("end_time", 0.0) or 0.0) for item in remapped_subtitles), default=0.0)
    if change_plan["timeline_changed"]:
        timeline_analysis = infer_timeline_analysis(
            remapped_subtitles,
            content_profile=content_profile,
            duration=output_duration_sec,
            editing_skill=editing_skill,
        )
        editing_accents = build_smart_editing_accents(
            keep_segments=effective_keep_segments,
            subtitle_items=remapped_subtitles,
            timeline_analysis=timeline_analysis,
            editing_skill=editing_skill,
            style=previous_smart_effect_style,
        )
    else:
        timeline_analysis = packaging_timeline_analysis(previous_packaging_timeline)
        editing_accents = (
            dict(previous_editing_accents)
            if isinstance(previous_editing_accents, dict)
            else None
        )
    if change_contract["timeline_changed"] or not previous_chapter_analysis.get("chapters"):
        chapter_analysis = await build_chapter_analysis_payload(
            source_name=str(job.source_name or ""),
            subtitle_items=remapped_subtitles,
            transcript_segments=[],
            content_profile=content_profile,
            duration_sec=output_duration_sec,
        )
        session.add(
            Artifact(
                job_id=job.id,
                artifact_type=ARTIFACT_TYPE_CHAPTER_ANALYSIS,
                data_json=chapter_analysis,
            )
        )
    else:
        chapter_analysis = previous_chapter_analysis

    should_replan_packaging = bool(change_contract["timeline_changed"] or change_contract["video_transform_changed"])
    if should_replan_packaging:
        creator_card = await _load_packaging_creator_card_for_job(session, job)
        packaging_plan = resolve_packaging_plan_for_job(
            str(job.id),
            content_profile=content_profile,
            creator_assets=list(getattr(creator_card, "assets", []) or []),
        )
        packaging_plan["insert"] = await _plan_insert_asset_slot(
            job_id=str(job.id),
            insert_plan=packaging_plan.get("insert"),
            subtitle_items=remapped_subtitles,
            content_profile=content_profile,
            timeline_analysis=timeline_analysis,
            allow_llm=False,
        )
        packaging_plan["music"] = await _plan_music_entry(
            music_plan=packaging_plan.get("music"),
            subtitle_items=remapped_subtitles,
            content_profile=content_profile,
            timeline_analysis=timeline_analysis,
        )
    else:
        packaging_plan = _manual_editor_packaging_plan_from_render_plan(
            None,
            render_plan_context=previous_render_plan_context,
        )
    projection_blocking_reasons = projection_output_fallback_reasons(subtitle_projection_repair)
    if projection_blocking_reasons:
        raise HTTPException(
            status_code=409,
            detail=(
                "manual editor apply produced a fallback subtitle projection result and was blocked from "
                "mutating the production timeline/render plan: " + ", ".join(projection_blocking_reasons)
            ),
        )
    insert_fallback_reasons = insert_plan_output_fallback_reasons(packaging_plan.get("insert"))
    if insert_fallback_reasons:
        raise HTTPException(
            status_code=409,
            detail=(
                "manual editor apply produced a fallback packaging plan result and was blocked from mutating "
                "the production timeline/render plan: " + ", ".join(insert_fallback_reasons)
            ),
        )
    editorial_segments = _build_editorial_segments_from_keep_segments(
        effective_keep_segments,
        source_duration_sec=source_duration_sec,
    )
    source_url = str((editorial_timeline.data_json or {}).get("source") or job.source_path or "")
    otio_style_payload = _build_otio_style_manual_tracks(
        editorial_segments,
        source_url=source_url,
        source_duration_sec=source_duration_sec,
    )
    editorial_payload = {
        "schema": otio_style_payload["schema"],
        "version": 2,
        "source": source_url,
        "source_duration_sec": otio_style_payload["source_duration_sec"],
        "output_duration_sec": otio_style_payload["output_duration_sec"],
        "tracks": otio_style_payload["tracks"],
        "subtitle_projection": {
            "mode": "ripple_keep_segments",
            "source": "latest_reviewed_subtitles",
            "base_subtitle_fingerprint": subtitle_fingerprint,
            "overrides": subtitle_override_payloads,
            "items": remapped_subtitles,
            "projected_count": len(remapped_subtitles),
        },
        "segments": editorial_segments,
        "analysis": {
            **timeline_analysis,
            "subtitle_projection_repair": subtitle_projection_repair,
            "manual_editor": {
                "applied": True,
                "base_timeline_id": str(editorial_timeline.id),
                "base_timeline_version": int(editorial_timeline.version or 1),
                "base_subtitle_fingerprint": subtitle_fingerprint,
                **change_contract,
                "subtitle_replacements": subtitle_replacement_payloads,
                "video_transform": video_transform,
                "video_summary": video_summary,
                "subtitle_projection_repair": subtitle_projection_repair,
                "note": str(request.note or "").strip() or None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }
    manual_editorial_timeline = Timeline(
        job_id=job.id,
        version=int(editorial_timeline.version or 0) + 1,
        timeline_type="editorial",
        data_json=editorial_payload,
    )
    try:
        manual_editorial_timeline.otio_data = export_to_otio(editorial_payload)
    except Exception:
        manual_editorial_timeline.otio_data = None
    session.add(manual_editorial_timeline)
    await session.flush()
    current_cut_analysis_payload = await _load_manual_editor_cut_analysis_payload(
        session,
        job=job,
        editorial_timeline_payload=None,
        editorial_analysis=dict(editorial_payload.get("analysis") or {}),
        source_subtitles=source_subtitle_dicts,
        smart_cut_rules=smart_cut_rules,
        content_profile=content_profile,
    )
    if change_contract["timeline_changed"]:
        reviewed_multimodal_trim_review_payload = await review_multimodal_trim_review_payload(
            _manual_editor_multimodal_trim_review_payload(
                cut_analysis_payload=current_cut_analysis_payload,
                source_name=str(job.source_name or ""),
                job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
            ),
            source_path=_resolve_manual_editor_source_path(job),
            source_meta=_manual_editor_multimodal_review_source_meta(job=job, content_profile=content_profile),
        )
    else:
        reviewed_multimodal_trim_review_payload = await _load_manual_editor_multimodal_trim_review_payload(
            session,
            job=job,
            cut_analysis_payload=current_cut_analysis_payload,
        )
    current_cut_analysis_payload = apply_multimodal_trim_review_to_cut_analysis(
        current_cut_analysis_payload,
        reviewed_multimodal_trim_review_payload,
    )
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_CUT_ANALYSIS,
            data_json=current_cut_analysis_payload,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,
            data_json=reviewed_multimodal_trim_review_payload,
        )
    )

    resolution_transform_changed = (
        previous_video_transform.get("resolution_mode") != video_transform.get("resolution_mode")
        or previous_video_transform.get("resolution_preset") != video_transform.get("resolution_preset")
    )
    export_resolution_mode = str(
        video_transform.get("resolution_mode")
        if resolution_transform_changed
        else packaging_plan.get("export_resolution_mode") or video_transform.get("resolution_mode") or "source"
    )
    export_resolution_preset = str(
        video_transform.get("resolution_preset")
        if resolution_transform_changed
        else packaging_plan.get("export_resolution_preset") or video_transform.get("resolution_preset") or "1080p"
    )
    export_frame_rate_mode = str(packaging_plan.get("export_frame_rate_mode") or "source")
    export_frame_rate_preset = str(packaging_plan.get("export_frame_rate_preset") or "30")
    effective_video_transform = {
        **video_transform,
        "resolution_mode": export_resolution_mode,
        "resolution_preset": export_resolution_preset,
        "frame_rate_mode": export_frame_rate_mode,
        "frame_rate_preset": export_frame_rate_preset,
    }
    previous_loudness = previous_render_plan_context["loudness"]
    previous_voice_processing = previous_render_plan_context["voice_processing"]

    rebuilt_render_plan = build_render_plan(
        editorial_timeline_id=manual_editorial_timeline.id,
        workflow_preset=(
            str(previous_render_plan_context["workflow_preset"] or "").strip()
            or str(job.workflow_template or "unboxing_standard")
        ),
        subtitle_version=int((previous_subtitles.get("version") or 1)),
        subtitle_style=str(packaging_plan.get("subtitle_style") or "bold_yellow_outline"),
        subtitle_motion_style=str(packaging_plan.get("subtitle_motion_style") or "motion_static"),
        smart_effect_style=str(packaging_plan.get("smart_effect_style") or "smart_effect_commercial"),
        target_lufs=float((previous_loudness.get("target_lufs") or -16.0)),
        peak_limit=float((previous_loudness.get("peak_limit") or -2.0)),
        noise_reduction=bool(previous_voice_processing.get("noise_reduction", True)),
        intro=packaging_plan.get("intro"),
        outro=packaging_plan.get("outro"),
        insert=packaging_plan.get("insert"),
        watermark=packaging_plan.get("watermark"),
        music=packaging_plan.get("music"),
        focus_plan=build_local_focus_plan(
            content_profile=content_profile,
            timeline_analysis=timeline_analysis,
        ),
        chapter_analysis=chapter_analysis,
        timeline_analysis=timeline_analysis,
        editing_skill=editing_skill,
        editing_accents=editing_accents,
        content_profile=content_profile,
        creative_profile=_job_creative_profile(job),
        dialogue_polish_plan=previous_render_plan_context["dialogue_polish_plan"],
        avatar_commentary_plan=previous_render_plan_context["avatar_commentary_plan"],
        hyperframes_options=effective_hyperframes_options,
        export_resolution_mode=export_resolution_mode,
        export_resolution_preset=export_resolution_preset,
        export_frame_rate_mode=export_frame_rate_mode,
        export_frame_rate_preset=export_frame_rate_preset,
    )
    rebuilt_render_plan["delivery"] = {
        "aspect_ratio": str(effective_video_transform.get("aspect_ratio") or "source"),
        "resolution_mode": export_resolution_mode,
        "resolution_preset": export_resolution_preset,
        "frame_rate_mode": export_frame_rate_mode,
        "frame_rate_preset": export_frame_rate_preset,
    }
    render_video_transform = {
        **effective_video_transform,
        "rotation_manual": bool(change_contract["rotation_changed"] or previous_video_transform.get("rotation_manual")),
    }
    rebuilt_render_plan["manual_editor"] = {
        "applied": True,
        **change_contract,
        "subtitle_replacements": subtitle_replacement_payloads,
        "video_transform": render_video_transform,
        "video_summary": video_summary,
        "base_render_plan_id": str(render_plan_timeline.id),
        "base_render_plan_version": int(render_plan_timeline.version or 1),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    manual_render_plan = await save_render_plan(job.id, rebuilt_render_plan, session)
    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_REFINE_DECISION_PLAN,
            data_json=_manual_editor_build_refine_decision_plan_from_render_plan(
                keep_segments=effective_keep_segments,
                source_duration_sec=source_duration_sec,
                mode="manual_refine",
                subtitle_fingerprint=subtitle_fingerprint,
                render_plan_data=None,
                render_plan_version=int(manual_render_plan.version or 1),
                cut_analysis=current_cut_analysis_payload,
                audio_defaults={
                    **dict(previous_loudness or {}),
                    **dict(previous_voice_processing or {}),
                },
                video_transform=render_video_transform,
                smart_cut_rules=smart_cut_rules,
                note=str(request.note or "").strip() or None,
                editorial_timeline_id=str(manual_editorial_timeline.id),
                editorial_timeline_version=int(manual_editorial_timeline.version or 1),
            ),
        )
    )
    manual_summary_updated_at = datetime.now(timezone.utc).isoformat()
    await _persist_manual_video_summary_evidence(
        session,
        job=job,
        video_summary=video_summary,
        updated_at=manual_summary_updated_at,
    )
    await _persist_manual_video_summary_source_context(
        session,
        job_id=job.id,
        video_summary=video_summary,
        updated_at=manual_summary_updated_at,
    )

    touch_runtime_refresh_hold(reason="manual_editor_apply", job_id=str(job.id), hold_seconds=120)
    rerun_contract = _manual_editor_rerun_plan(change_contract)
    rerun_steps = list(rerun_contract.get("rerun_steps") or [])
    if rerun_steps:
        rerun_plan = JobRerunPlan(
            rerun_start_step=str(rerun_contract["rerun_start_step"]),
            rerun_steps=rerun_steps,
            issue_codes=[_manual_editor_rerun_issue_code(change_contract)],
            note=str(request.note or "").strip() or "manual_editor_apply",
        )
        await execute_job_rerun_plan(
            session,
            job=job,
            steps=list(job.steps or []),
            plan=rerun_plan,
            via="manual_editor",
        )
    else:
        job.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return ManualEditorApplyOut(
        job_id=str(job.id),
        timeline_id=str(manual_editorial_timeline.id),
        timeline_version=int(manual_editorial_timeline.version or 1),
        render_plan_id=str(manual_render_plan.id),
        render_plan_version=int(manual_render_plan.version or 1),
        keep_segment_count=len(effective_keep_segments),
        projected_subtitle_count=len(remapped_subtitles),
        job_status=str(job.status or "processing"),
        change_scope=str(change_contract["change_scope"]),
        render_strategy=str(change_contract["render_strategy"]),
        rerun_steps=rerun_steps,
        detail=_manual_editor_apply_detail(str(change_contract["change_scope"])),
    )


@router.get("/{job_id}/content-profile", response_model=ContentProfileReviewOut)
async def get_content_profile(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if str(job.status or "").strip() == "needs_review":
        touch_runtime_refresh_hold(reason="content_profile_review", job_id=str(job_id), hold_seconds=90)

    from roughcut.db.models import Artifact

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(_CONTENT_PROFILE_ARTIFACT_TYPES),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()
    draft = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_draft"), None)
    final = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_final"), None)
    base_profile = next((item.data_json for item in artifacts if item.artifact_type == "content_profile"), None)
    has_draft_artifact = isinstance(draft, dict) and bool(draft)
    if not isinstance(draft, dict) or not draft:
        draft = base_profile
    if not isinstance(final, dict) or not final:
        final = None if has_draft_artifact else base_profile
    settings = get_settings()
    strategy_gate_confirmations = await _load_latest_strategy_review_gate_confirmations(session, job_id=job_id)
    if isinstance(draft, dict):
        draft = apply_current_content_profile_review_policy(draft, settings=settings)
        draft = attach_content_profile_capability_orchestration(
            _ensure_content_understanding_payload(draft),
            job=job,
            strategy_review_gate_confirmations=strategy_gate_confirmations,
        )
    if isinstance(final, dict):
        final = apply_current_content_profile_review_policy(final, settings=settings)
        final = attach_content_profile_capability_orchestration(
            _ensure_content_understanding_payload(final),
            job=job,
            strategy_review_gate_confirmations=strategy_gate_confirmations,
        )
    reviewed_subtitle_excerpt = await _build_current_reviewed_subtitle_excerpt(job_id, session)
    if reviewed_subtitle_excerpt:
        if isinstance(draft, dict):
            draft = dict(draft)
            draft["reviewed_subtitle_excerpt"] = reviewed_subtitle_excerpt
        if isinstance(final, dict):
            final = dict(final)
            final["reviewed_subtitle_excerpt"] = reviewed_subtitle_excerpt

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    active_profile = final if isinstance(final, dict) and final else draft if isinstance(draft, dict) and draft else {}
    automation_review = active_profile.get("automation_review") if isinstance(active_profile, dict) else {}
    user_memory = await load_content_profile_user_memory(session, subject_domain=(active_profile or {}).get("subject_domain"))
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)

    review_step_detail = None
    if review_step is not None:
        review_step_detail = str((review_step.metadata_ or {}).get("detail") or "").strip() or None
    review_reasons = list((automation_review or {}).get("review_reasons") or [])
    blocking_reasons = list((automation_review or {}).get("blocking_reasons") or [])
    if review_step is not None:
        review_reasons = review_reasons or list((review_step.metadata_ or {}).get("review_reasons") or [])
        blocking_reasons = blocking_reasons or list((review_step.metadata_ or {}).get("blocking_reasons") or [])
    identity_review = (
        (active_profile or {}).get("identity_review")
        if isinstance(active_profile, dict)
        else None
    )
    if identity_review is None and review_step is not None:
        candidate = (review_step.metadata_ or {}).get("identity_review")
        identity_review = candidate if isinstance(candidate, dict) else None
    evidence = await _load_content_profile_review_evidence(job_id, session)
    strategy_review_gates = build_strategy_review_gates_artifact_payload(
        active_profile,
        confirmations=strategy_gate_confirmations,
    )
    if strategy_review_gates is None:
        latest_strategy_gates = await _load_latest_strategy_review_gates_artifact(session, job_id=job_id)
        strategy_review_gates = (
            dict(latest_strategy_gates.data_json or {})
            if latest_strategy_gates is not None and isinstance(latest_strategy_gates.data_json, dict)
            else None
        )

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "pending",
        review_step_detail=review_step_detail,
        review_reasons=review_reasons,
        blocking_reasons=blocking_reasons,
        identity_review=identity_review,
        **evidence,
        workflow_mode=str(getattr(job, "workflow_mode", "") or "standard_edit"),
        enhancement_modes=list(getattr(job, "enhancement_modes", []) or []),
        product_controls=(active_profile.get("product_controls") if isinstance(active_profile, dict) else {}) or {},
        strategy_review_gates=strategy_review_gates,
        draft=draft,
        final=final,
        memory=memory,
    )


@router.get("/stats/content-profile-memory", response_model=ContentProfileMemoryStatsOut)
async def get_content_profile_memory_stats(
    subject_domain: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    user_memory = await load_content_profile_user_memory(session, subject_domain=subject_domain)
    subject_domain_result = await session.execute(
        select(distinct(ContentProfileCorrection.subject_domain))
        .where(ContentProfileCorrection.subject_domain.is_not(None))
        .order_by(ContentProfileCorrection.subject_domain)
    )
    subject_domains = [item for item in subject_domain_result.scalars().all() if item]

    correction_result = await session.execute(
        select(ContentProfileCorrection).order_by(ContentProfileCorrection.created_at.desc()).limit(240)
    )
    corrections = correction_result.scalars().all()

    keyword_result = await session.execute(select(ContentProfileKeywordStat))
    keyword_stats = keyword_result.scalars().all()

    total_corrections = sum(
        1
        for item in corrections
        if not subject_domain or item.subject_domain in {None, subject_domain}
    )
    total_keywords = sum(
        int(item.usage_count or 0)
        for item in keyword_stats
        if item.scope_type == "global"
        or (subject_domain and item.scope_type == "subject_domain" and item.scope_value == subject_domain)
    )

    return ContentProfileMemoryStatsOut(
        scope="subject_domain" if subject_domain else "global",
        subject_domain=subject_domain,
        subject_domains=subject_domains,
        total_corrections=total_corrections,
        total_keywords=total_keywords,
        total_learned_hotwords=len((user_memory or {}).get("learned_hotwords") or []),
        field_preferences=_build_field_preferences(corrections, subject_domain=subject_domain, limit=6),
        keyword_preferences=_build_keyword_preferences(keyword_stats, subject_domain=subject_domain, limit=18),
        learned_hotwords=list((user_memory or {}).get("learned_hotwords") or [])[:24],
        recent_corrections=_build_recent_corrections(corrections, subject_domain=subject_domain, limit=12),
        cloud=build_content_profile_memory_cloud(user_memory),
    )


@router.get("/stats/content-profile-approval", response_model=ContentProfileApprovalStatsOut)
async def get_content_profile_approval_stats():
    settings = get_settings()
    required_accuracy = float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9)
    minimum_sample_size = int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20)
    summary = summarize_content_profile_review_stats(
        min_accuracy=required_accuracy,
        min_samples=minimum_sample_size,
    )
    return ContentProfileApprovalStatsOut(
        updated_at=summary["updated_at"],
        auto_review_enabled=bool(getattr(settings, "auto_confirm_content_profile", False)),
        review_threshold=float(getattr(settings, "content_profile_review_threshold", 0.9) or 0.9),
        required_accuracy=summary["required_accuracy"],
        minimum_sample_size=summary["minimum_sample_size"],
        gate_passed=summary["gate_passed"],
        detail=str(summary["detail"]),
        measured_accuracy=summary["measured_accuracy"],
        sample_size=int(summary["sample_size"]),
        manual_review_total=int(summary["manual_review_total"]),
        approved_without_changes=int(summary["approved_without_changes"]),
        corrected_after_review=int(summary["corrected_after_review"]),
        eligible_manual_review_total=int(summary["eligible_manual_review_total"]),
        eligible_approved_without_changes=int(summary["eligible_approved_without_changes"]),
        eligible_corrected_after_review=int(summary["eligible_corrected_after_review"]),
        eligible_approval_accuracy=summary["eligible_approval_accuracy"],
    )


@router.post("/{job_id}/open-folder", response_model=OpenFolderOut)
async def open_job_folder(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    target_path, kind = await _resolve_job_open_target(job, session)
    if not target_path:
        raise HTTPException(status_code=409, detail="当前任务没有可打开的本地文件夹")

    try:
        _open_in_file_manager(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{exc}") from exc

    resolved_path, resolved_kind = describe_file_manager_target(target_path)
    return OpenFolderOut(path=resolved_path, kind=resolved_kind or kind)


@router.get("/{job_id}/content-profile/thumbnail")
async def get_content_profile_thumbnail(
    job_id: uuid.UUID,
    index: int = 0,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if index < 0 or index > 2:
        raise HTTPException(status_code=400, detail="Thumbnail index out of range")

    try:
        thumbnail = await _ensure_content_profile_thumbnail(job, index=index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/{job_id}/cover-thumbnail")
async def get_job_cover_thumbnail(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.artifacts), selectinload(Job.publication_attempts))
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cover_path = _resolve_job_queue_cover_path(job)
    if cover_path is None:
        raise HTTPException(status_code=404, detail="Cover thumbnail not found")
    return FileResponse(
        cover_path,
        media_type=_media_type_for_path(cover_path),
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/{job_id}/content-profile/thumbnails/warm")
async def warm_content_profile_thumbnails(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for index in (0, 1, 2):
        _spawn_content_profile_thumbnail_generation(job, index=index)
    return {"status": "accepted", "job_id": str(job_id)}


async def _load_latest_strategy_review_gate_confirmations(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> dict[str, Any]:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type == ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS,
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifact = result.scalars().first()
    return dict(artifact.data_json or {}) if artifact is not None and isinstance(artifact.data_json, dict) else {}


async def _load_latest_strategy_review_gates_artifact(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> Artifact | None:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type == ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    return result.scalars().first()


@router.post("/{job_id}/strategy-review-gates/confirm")
async def confirm_strategy_review_gates(
    job_id: uuid.UUID,
    body: StrategyReviewGateConfirmIn,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    gate_artifact = await _load_latest_strategy_review_gates_artifact(session, job_id=job_id)
    if gate_artifact is None or not isinstance(gate_artifact.data_json, dict):
        raise HTTPException(status_code=404, detail="Strategy review gates not found")
    gate_payload = dict(gate_artifact.data_json)
    pipeline_plan = gate_payload.get("pipeline_plan")
    if not isinstance(pipeline_plan, dict):
        raise HTTPException(status_code=409, detail="Strategy review gates artifact has no pipeline plan")
    classification = gate_payload.get("classification") if isinstance(gate_payload.get("classification"), dict) else {}
    review_gate_status = gate_payload.get("review_gate_status") if isinstance(gate_payload.get("review_gate_status"), dict) else {}
    default_gate_ids = [
        str(item or "").strip()
        for item in list(review_gate_status.get("blocking_gate_ids") or [])
        if str(item or "").strip()
    ]
    requested_gate_ids = [
        str(item or "").strip()
        for item in list(body.gate_ids or default_gate_ids)
        if str(item or "").strip()
    ]
    if not requested_gate_ids:
        raise HTTPException(status_code=409, detail="No blocking strategy review gates require confirmation")

    existing_payload = await _load_latest_strategy_review_gate_confirmations(session, job_id=job_id)
    existing_confirmations = normalize_strategy_review_gate_confirmations(
        existing_payload,
        pipeline_plan=pipeline_plan,
        classification=classification,
    )
    confirmation_payload = build_strategy_review_gate_confirmations_payload(
        gate_ids=requested_gate_ids,
        pipeline_plan=pipeline_plan,
        classification=classification,
        status=body.status,
        note=body.note or "",
        actor="operator",
    )
    confirmation_payload["confirmations"] = {
        **existing_confirmations,
        **dict(confirmation_payload.get("confirmations") or {}),
    }
    updated_gate_payload = build_strategy_review_gates_artifact_payload(
        {
            "capability_orchestration": {
                "strategy_type": gate_payload.get("strategy_type") or pipeline_plan.get("strategy_type"),
                "classification": classification,
                "pipeline_plan": pipeline_plan,
            }
        },
        confirmations=confirmation_payload,
    )
    if updated_gate_payload is None:
        raise HTTPException(status_code=409, detail="Unable to rebuild strategy review gates")

    session.add(
        Artifact(
            job_id=job.id,
            step_id=gate_artifact.step_id,
            artifact_type=ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS,
            data_json=confirmation_payload,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            step_id=gate_artifact.step_id,
            artifact_type=ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
            data_json=updated_gate_payload,
        )
    )
    job.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return updated_gate_payload


@router.post("/{job_id}/content-profile/confirm", response_model=ContentProfileReviewOut)
async def confirm_content_profile(
    job_id: uuid.UUID,
    body: ContentProfileConfirmIn,
    session: AsyncSession = Depends(get_session),
):
    from datetime import datetime, timezone

    from roughcut.db.models import Artifact

    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    touch_runtime_refresh_hold(reason="content_profile_confirm", job_id=str(job_id), hold_seconds=120)

    artifact_result = await session.execute(
        select(Artifact)
        .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        .order_by(Artifact.created_at.desc())
    )
    draft_artifact = artifact_result.scalars().first()
    if not draft_artifact:
        raise HTTPException(status_code=404, detail="Content profile draft not found")

    subtitle_item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_items = subtitle_item_result.scalars().all()
    correction_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
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
        for correction in correction_result.scalars().all()
        if correction.human_decision == "accepted"
    ]
    reviewed_subtitle_excerpt = build_reviewed_transcript_excerpt(
        [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ],
        accepted_corrections,
    )

    user_feedback = body.model_dump(exclude_none=True)
    workflow_mode = str(user_feedback.pop("workflow_mode", "") or getattr(job, "workflow_mode", "standard_edit"))
    enhancement_modes = list(user_feedback.pop("enhancement_modes", None) or getattr(job, "enhancement_modes", []) or [])
    final_profile = await apply_content_profile_feedback(
        draft_profile=draft_artifact.data_json or {},
        source_name=job.source_name,
        workflow_template=job.workflow_template,
        user_feedback=user_feedback,
        reviewed_subtitle_excerpt=reviewed_subtitle_excerpt,
        accepted_corrections=accepted_corrections,
        skip_model_refinement=True,
    )
    final_profile = strip_publication_only_profile_fields(final_profile)
    final_profile["user_feedback"] = user_feedback
    manual_review_outcome = record_content_profile_manual_review(
        job_id=str(job.id),
        draft_artifact_id=str(draft_artifact.id),
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
    )
    automation_review = final_profile.get("automation_review") if isinstance(final_profile, dict) else {}
    if isinstance(automation_review, dict):
        settings = get_settings()
        accuracy_gate = build_content_profile_auto_review_gate(
            min_accuracy=float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9),
            min_samples=int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20),
        )
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
    final_profile["manual_review_outcome"] = manual_review_outcome
    strategy_gate_confirmations = await _load_latest_strategy_review_gate_confirmations(session, job_id=job_id)
    enriched_final_profile = attach_content_profile_capability_orchestration(
        _ensure_content_understanding_payload(final_profile),
        job=job,
        strategy_review_gate_confirmations=strategy_gate_confirmations,
    )
    final_profile = enriched_final_profile if isinstance(enriched_final_profile, dict) else final_profile
    strategy_review_gates_payload = build_strategy_review_gates_artifact_payload(
        final_profile,
        confirmations=strategy_gate_confirmations,
    )
    strategy_storyboard_review_payload = build_strategy_storyboard_review_artifact_payload(final_profile)
    strategy_timeline_preview_payload = build_strategy_timeline_preview_artifact_payload(final_profile)

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    if review_step:
        review_step.status = "done"
        review_step.finished_at = datetime.now(timezone.utc)
        review_step.error_message = None

    artifact = Artifact(
        job_id=job.id,
        step_id=review_step.id if review_step else None,
        artifact_type="content_profile_final",
        data_json=final_profile,
    )
    session.add(artifact)
    session.add(
        Artifact(
            job_id=job.id,
            step_id=review_step.id if review_step else None,
            artifact_type="downstream_context",
            data_json=build_downstream_context(
                final_profile,
                strategy_review_gates=strategy_review_gates_payload,
                strategy_storyboard_review=strategy_storyboard_review_payload,
                strategy_timeline_preview=strategy_timeline_preview_payload,
            ),
        )
    )
    if strategy_review_gates_payload is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=review_step.id if review_step else None,
                artifact_type=ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
                data_json=strategy_review_gates_payload,
            )
        )
    if strategy_storyboard_review_payload is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=review_step.id if review_step else None,
                artifact_type=ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
                data_json=strategy_storyboard_review_payload,
            )
        )
    if strategy_timeline_preview_payload is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=review_step.id if review_step else None,
                artifact_type=ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
                data_json=strategy_timeline_preview_payload,
            )
        )
    await record_content_profile_feedback_memory(
        session,
        job=job,
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
        user_feedback=user_feedback,
    )
    await _persist_confirmed_content_profile_glossary_terms(
        session,
        job=job,
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
        user_feedback=user_feedback,
    )

    job.workflow_mode = normalize_workflow_mode(workflow_mode)
    job.enhancement_modes = normalize_enhancement_modes(enhancement_modes)
    job.status = "processing"
    job.updated_at = datetime.now(timezone.utc)
    await session.flush()
    apply_runtime_overrides(
        {
            "default_job_workflow_mode": job.workflow_mode,
            "default_job_enhancement_modes": list(job.enhancement_modes or []),
        }
    )
    user_memory = await load_content_profile_user_memory(
        session,
        subject_domain=str(final_profile.get("subject_domain") or ""),
    )
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)
    await session.commit()

    review_step_detail = None
    if review_step is not None:
        review_step_detail = str((review_step.metadata_ or {}).get("detail") or "").strip() or None
    automation_review = final_profile.get("automation_review") if isinstance(final_profile, dict) else {}
    identity_review = final_profile.get("identity_review") if isinstance(final_profile, dict) else None
    evidence = await _load_content_profile_review_evidence(job_id, session)
    draft_profile = attach_content_profile_capability_orchestration(
        _ensure_content_understanding_payload(draft_artifact.data_json),
        job=job,
        strategy_review_gate_confirmations=strategy_gate_confirmations,
    )
    final_profile = attach_content_profile_capability_orchestration(
        _ensure_content_understanding_payload(final_profile),
        job=job,
        strategy_review_gate_confirmations=strategy_gate_confirmations,
    )
    response_strategy_review_gates = build_strategy_review_gates_artifact_payload(
        final_profile,
        confirmations=strategy_gate_confirmations,
    )

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "done",
        review_step_detail=review_step_detail,
        review_reasons=list((automation_review or {}).get("review_reasons") or []),
        blocking_reasons=list((automation_review or {}).get("blocking_reasons") or []),
        identity_review=identity_review if isinstance(identity_review, dict) else None,
        **evidence,
        workflow_mode=job.workflow_mode,
        enhancement_modes=list(job.enhancement_modes or []),
        product_controls=(final_profile.get("product_controls") if isinstance(final_profile, dict) else {}) or {},
        strategy_review_gates=response_strategy_review_gates,
        draft=draft_profile,
        final=final_profile,
        memory=memory,
    )


@router.get("/{job_id}/download")
async def get_download_url(
    job_id: uuid.UUID,
    variant: str = "packaged",
    session: AsyncSession = Depends(get_session),
):
    variant_value = str(variant or "packaged").strip().lower()
    if variant_value not in {"packaged", "plain"}:
        raise HTTPException(status_code=400, detail="variant must be 'packaged' or 'plain'")
    render_output, artifact_payload = await _load_download_context(job_id, session)
    download_path = _resolve_download_variant_path(render_output, artifact_payload, variant_value)
    _download_file_cache_set(job_id, variant_value, download_path)
    return {
        "url": f"/api/v1/jobs/{job_id}/download/file?variant={variant_value}",
        "expires_in": None,
    }


@router.get("/{job_id}/download/files", response_model=JobDownloadFilesOut)
async def list_downloadable_files(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    render_output, artifact_payload = await _load_download_context(job_id, session)
    files = _collect_downloadable_files(render_output, artifact_payload)
    return JobDownloadFilesOut(job_id=str(job_id), files=[JobDownloadFileOut(**item) for item in files])


@router.post("/{job_id}/download/zip")
async def download_selected_files_zip(
    job_id: uuid.UUID,
    body: JobDownloadZipIn,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    render_output, artifact_payload = await _load_download_context(job_id, session)
    files = _collect_downloadable_files(render_output, artifact_payload)
    file_map = {item["id"]: item for item in files}
    selected_ids = [str(item or "").strip() for item in body.file_ids if str(item or "").strip()]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个文件")
    if len(selected_ids) > 50:
        raise HTTPException(status_code=400, detail="一次最多下载 50 个文件")

    missing_ids = [item for item in selected_ids if item not in file_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"文件不存在或不可下载：{', '.join(missing_ids[:5])}")

    download_dir = Path(tempfile.gettempdir()) / "roughcut_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    zip_path = download_dir / f"{job_id}_{uuid.uuid4().hex}.zip"
    used_names: set[str] = set()
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for file_id in selected_ids:
                item = file_map[file_id]
                source_path = Path(str(item["_path"]))
                if not source_path.exists() or not source_path.is_file():
                    raise HTTPException(status_code=404, detail=f"文件不存在：{item['filename']}")
                archive.write(source_path, arcname=_unique_zip_member_name(source_path.name, used_names))
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise

    background_tasks.add_task(zip_path.unlink, missing_ok=True)
    filename = f"{_sanitize_download_filename(Path(job.source_name).stem or 'roughcut')}_outputs.zip"
    return FileResponse(
        path=zip_path,
        filename=filename,
        media_type="application/zip",
        background=background_tasks,
    )


@router.get("/{job_id}/download/file")
async def download_rendered_file(
    job_id: uuid.UUID,
    variant: str = "packaged",
    disposition: str = "attachment",
):
    variant_value = str(variant or "packaged").strip().lower()
    if variant_value not in {"packaged", "plain"}:
        raise HTTPException(status_code=400, detail="variant must be 'packaged' or 'plain'")
    disposition_value = str(disposition or "attachment").strip().lower()
    if disposition_value not in {"attachment", "inline"}:
        raise HTTPException(status_code=400, detail="disposition must be 'attachment' or 'inline'")

    cached_path = _download_file_cache_get(job_id, variant_value)
    if cached_path is not None:
        if disposition_value == "inline":
            return _inline_file_response(cached_path)
        return FileResponse(path=cached_path, filename=cached_path.name, media_type=_media_type_for_path(cached_path))

    async with get_session_factory()() as session:
        render_output, artifact_payload = await _load_download_context(job_id, session)
        download_path = _resolve_download_variant_path(render_output, artifact_payload, variant_value)
    _download_file_cache_set(job_id, variant_value, download_path)
    if disposition_value == "inline":
        return _inline_file_response(download_path)
    return FileResponse(path=download_path, filename=download_path.name, media_type=_media_type_for_path(download_path))


def _normalize_publication_query_platforms(platforms: list[str] | None) -> list[str] | None:
    normalized: list[str] = []
    for item in platforms or []:
        for part in str(item or "").split(","):
            platform = normalize_publication_platform(part)
            if platform and platform not in normalized:
                normalized.append(platform)
    return normalized or None


@router.get("/{job_id}/publication/plan")
async def get_job_publication_plan(
    job_id: uuid.UUID,
    creator_profile_id: str | None = None,
    platforms: list[str] | None = Query(default=None),
    dynamic_options: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    requested_platforms = _normalize_publication_query_platforms(platforms)
    job, render_output, packaging, creator_profile = await _load_publication_inputs(
        job_id=job_id,
        creator_profile_id=creator_profile_id,
        session=session,
    )
    existing_attempts = await list_publication_attempts(session, job_id=str(job_id))
    platform_options = await _resolve_job_publication_platform_options(
        session=session,
        job=job,
        render_output=render_output,
        packaging=packaging,
        creator_profile=creator_profile,
        existing_attempts=existing_attempts,
        requested_platforms=requested_platforms,
        requested_platform_options=None,
        resolve_dynamic_options=dynamic_options,
    )
    return build_publication_plan(
        job=job,
        render_output=render_output,
        platform_packaging=packaging,
        creator_profile=creator_profile,
        requested_platforms=requested_platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
    )


@router.post("/{job_id}/publication/materials")
async def prepare_job_publication_materials(
    job_id: uuid.UUID,
    payload: PublicationSubmitIn,
    session: AsyncSession = Depends(get_session),
):
    job, render_output, packaging, creator_profile = await _load_publication_inputs(
        job_id=job_id,
        creator_profile_id=payload.creator_profile_id,
        session=session,
    )
    existing_attempts = await list_publication_attempts(session, job_id=str(job_id))
    material_generation: dict[str, Any] | None = None
    if _job_publication_packaging_needs_generation(packaging, requested_platforms=payload.platforms):
        material_generation = await _generate_job_publication_materials(
            job=job,
            render_output=render_output,
            creator_profile=creator_profile,
            creator_profile_id=payload.creator_profile_id,
            platforms=payload.platforms,
        )
        job, render_output, packaging, creator_profile = await _load_publication_inputs(
            job_id=job_id,
            creator_profile_id=payload.creator_profile_id,
            session=session,
        )
        existing_attempts = await list_publication_attempts(session, job_id=str(job_id))
    platform_options = await _resolve_job_publication_platform_options(
        session=session,
        job=job,
        render_output=render_output,
        packaging=packaging,
        creator_profile=creator_profile,
        existing_attempts=existing_attempts,
        requested_platforms=payload.platforms,
        requested_platform_options=payload.platform_options,
    )
    plan = build_publication_plan(
        job=job,
        render_output=render_output,
        platform_packaging=packaging,
        creator_profile=creator_profile,
        requested_platforms=payload.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
    )
    plan, job, render_output, packaging, creator_profile = await _maybe_auto_heal_job_publication_cover_plan(
        plan=plan,
        job=job,
        render_output=render_output,
        packaging=packaging,
        creator_profile=creator_profile,
        creator_profile_id=payload.creator_profile_id,
        requested_platforms=payload.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
        session=session,
    )
    if material_generation is not None:
        plan = {**plan, "material_generation": material_generation}
    return plan


def _build_job_publication_executor_gate_response(
    plan: dict[str, Any],
    *,
    blocked_reasons: list[str] | None = None,
    publication_executor_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_status = publication_plan_status(plan)
    return {
        **plan,
        "status": "manual_handoff" if plan_status == "manual_handoff" else "blocked",
        "publish_ready": False,
        "blocked_reasons": blocked_reasons or plan.get("blocked_reasons") or ["当前物料或账号暂不满足发布条件。"],
        "manual_handoff_ready": publication_plan_is_manual_handoff_ready(plan),
        "manual_handoff_targets": list(plan.get("manual_handoff_targets") or []),
        "publication_executor_preflight": publication_executor_preflight or {},
        "created_attempts": [],
    }


@router.post("/{job_id}/publication/publish")
async def publish_job_to_bound_platforms(
    job_id: uuid.UUID,
    payload: PublicationSubmitIn,
    session: AsyncSession = Depends(get_session),
):
    job, render_output, packaging, creator_profile = await _load_publication_inputs(
        job_id=job_id,
        creator_profile_id=payload.creator_profile_id,
        session=session,
    )
    existing_attempts = await list_publication_attempts(session, job_id=str(job_id))
    material_generation: dict[str, Any] | None = None
    if _job_publication_packaging_needs_generation(packaging, requested_platforms=payload.platforms):
        recovered_plan = build_publication_plan(
            job=job,
            render_output=render_output,
            platform_packaging=packaging,
            creator_profile=creator_profile,
            requested_platforms=payload.platforms,
            platform_options=payload.platform_options,
            existing_attempts=existing_attempts,
        )
        recovered_media_source = (
            recovered_plan.get("media_source_contract")
            if isinstance(recovered_plan.get("media_source_contract"), dict)
            else {}
        ).get("source")
        can_use_materialized_contract = (
            recovered_media_source == "materialized_attempt_payload"
            and publication_plan_is_publishable(recovered_plan)
        )
        if not can_use_materialized_contract:
            material_generation = await _generate_job_publication_materials(
                job=job,
                render_output=render_output,
                creator_profile=creator_profile,
                creator_profile_id=payload.creator_profile_id,
                platforms=payload.platforms,
            )
            job, render_output, packaging, creator_profile = await _load_publication_inputs(
                job_id=job_id,
                creator_profile_id=payload.creator_profile_id,
                session=session,
            )
            existing_attempts = await list_publication_attempts(session, job_id=str(job_id))
    platform_options = await _resolve_job_publication_platform_options(
        session=session,
        job=job,
        render_output=render_output,
        packaging=packaging,
        creator_profile=creator_profile,
        existing_attempts=existing_attempts,
        requested_platforms=payload.platforms,
        requested_platform_options=payload.platform_options,
    )
    plan = build_publication_plan(
        job=job,
        render_output=render_output,
        platform_packaging=packaging,
        creator_profile=creator_profile,
        requested_platforms=payload.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
    )
    plan, job, render_output, packaging, creator_profile = await _maybe_auto_heal_job_publication_cover_plan(
        plan=plan,
        job=job,
        render_output=render_output,
        packaging=packaging,
        creator_profile=creator_profile,
        creator_profile_id=payload.creator_profile_id,
        requested_platforms=payload.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
        session=session,
    )
    if not publication_plan_is_publishable(plan):
        response = _build_job_publication_executor_gate_response(plan)
        if material_generation is not None:
            response["material_generation"] = material_generation
        return response
    browser_agent_targets = [
        target
        for target in (plan.get("targets") or [])
        if isinstance(target, dict) and publication_adapter_requires_browser_agent(target.get("adapter"))
    ]
    if browser_agent_targets:
        settings = get_settings()
        agent_ready = await check_publication_browser_agent_ready(
            browser_agent_base_url=str(getattr(settings, "publication_browser_agent_base_url", "") or ""),
            auth_token=str(getattr(settings, "publication_browser_agent_auth_token", "") or ""),
            target_platforms=[str(target.get("platform") or "") for target in browser_agent_targets],
            target_profile_ids=[
                str(target.get("browser_profile_id") or target.get("credential_ref") or "")
                for target in browser_agent_targets
            ],
            skip_creator_session_platforms=[
                str(target.get("platform") or "")
                for target in browser_agent_targets
                if str(target.get("platform") or "").strip().lower() == "youtube"
            ],
            request_timeout_sec=max(5, int(getattr(settings, "publication_browser_agent_timeout_sec", 60) or 60)),
        )
        if not agent_ready.get("ready"):
            return _build_job_publication_executor_gate_response(
                plan,
                blocked_reasons=[
                    *(plan.get("blocked_reasons") or []),
                    str(agent_ready.get("message") or "browser-agent 不支持正式发布。"),
                ],
                publication_executor_preflight=agent_ready,
            )
    result = await submit_publication_attempts(session, plan)
    await session.commit()
    _dispatch_publication_worker_tick(len(result.get("created_attempts") or []))
    if material_generation is not None:
        result["material_generation"] = material_generation
    return result


def _normalize_publish_platform_options_payload(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_value, dict):
            continue
        key = str(raw_key or "").strip().lower().replace("_", "-")
        if key:
            normalized[key] = dict(raw_value)
    return normalized


def _merge_publish_platform_options(
    base: dict[str, dict[str, Any]],
    override: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {platform: dict(options) for platform, options in base.items()}
    for platform, options in override.items():
        current = dict(merged.get(platform) or {})
        for key, value in options.items():
            if key == "platform_specific_overrides" and isinstance(value, dict):
                nested = dict(current.get("platform_specific_overrides") or {}) if isinstance(current.get("platform_specific_overrides"), dict) else {}
                nested.update(value)
                current["platform_specific_overrides"] = nested
            else:
                current[key] = value
        merged[platform] = current
    return merged


def _job_collection_strategy_match_text(job: Job) -> str:
    values = [
        getattr(job, "task_brief", ""),
        getattr(job, "source_name", ""),
        getattr(job, "source_path", ""),
        getattr(job, "output_dir", ""),
    ]
    platform_targets = getattr(job, "platform_targets_json", None)
    if isinstance(platform_targets, list):
        values.extend(str(item or "") for item in platform_targets)
    return " ".join(str(item or "") for item in values)


def _collection_strategy_candidates(collection_strategy: dict[str, Any]) -> list[str]:
    candidates = [
        str(item).strip()
        for item in (collection_strategy.get("candidate_collections") or [])
        if str(item).strip()
    ]
    for rule in collection_strategy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        collection_name = str(rule.get("collection_name") or "").strip()
        if collection_name and collection_name not in candidates:
            candidates.append(collection_name)
    fallback = str(collection_strategy.get("default_collection_name") or "").strip()
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _fallback_collection_name_from_natural_strategy(
    collection_strategy: dict[str, Any],
    job: Job,
) -> tuple[str, dict[str, Any] | None]:
    match_text = _job_collection_strategy_match_text(job).casefold()
    for rule in collection_strategy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        collection_name = str(rule.get("collection_name") or "").strip()
        if not collection_name:
            continue
        evidence_text = " ".join(
            [
                str(rule.get("natural_language_rule") or ""),
                " ".join(str(item or "") for item in (rule.get("examples") or [])),
            ]
        ).casefold()
        evidence_terms = [
            term
            for term in re.split(r"[\s,，、/；;。:.：()（）]+", evidence_text)
            if len(term.strip()) >= 2
        ]
        if any(term in match_text for term in evidence_terms):
            return collection_name, rule
    fallback = str(collection_strategy.get("default_collection_name") or "").strip()
    return fallback, None


def _collection_name_from_rule_strategy(
    collection_strategy: dict[str, Any],
    job: Job,
) -> tuple[str, dict[str, Any]]:
    collection_name, matched_rule = _fallback_collection_name_from_natural_strategy(collection_strategy, job)
    if not collection_name:
        return "", {"source": "empty_rule_result"}
    return collection_name, {
        "source": "rule_based",
        "matched_rule": matched_rule or {},
        "selection_mode": "rule_match" if matched_rule else "default_collection_name",
    }


async def _collection_name_from_llm_strategy(
    collection_strategy: dict[str, Any],
    job: Job,
) -> tuple[str, dict[str, Any]]:
    candidates = _collection_strategy_candidates(collection_strategy)
    if not candidates:
        return "", {"source": "empty_candidates"}
    rules = [
        {
            "collection_name": str(rule.get("collection_name") or "").strip(),
            "natural_language_rule": str(rule.get("natural_language_rule") or "").strip(),
            "examples": [str(item) for item in (rule.get("examples") or [])],
        }
        for rule in (collection_strategy.get("rules") or [])
        if isinstance(rule, dict) and str(rule.get("collection_name") or "").strip()
    ]
    prompt = f"""
你是 RoughCut 的发布合集分类器。请根据视频任务信息，从候选合集中选择唯一一个最合适的合集。

分类依据：
{collection_strategy.get("classification_basis") or "根据任务想法、素材文件名、路径、标题、简介和标签理解视频主题。"}

候选合集：
{json.dumps(candidates, ensure_ascii=False)}

自然语言规则：
{json.dumps(rules, ensure_ascii=False)}

任务信息：
{_job_collection_strategy_match_text(job)}

只返回 JSON：
{{
  "collection_name": "必须是候选合集之一；无法判断时返回兜底合集",
  "reason": "一句话说明为什么"
}}
""".strip()
    try:
        with llm_task_route("publication", search_enabled=False, settings=get_settings()):
            response = await get_reasoning_provider().complete(
                [Message(role="user", content=prompt)],
                temperature=0.0,
                max_tokens=300,
                json_mode=True,
            )
        payload = response.as_json()
        collection_name = str((payload or {}).get("collection_name") or "").strip()
        if collection_name in candidates:
            return collection_name, {
                "source": "llm",
                "model": response.model,
                "reason": str((payload or {}).get("reason") or "").strip(),
                "usage": response.usage,
            }
    except Exception as exc:
        fallback, matched_rule = _fallback_collection_name_from_natural_strategy(collection_strategy, job)
        return fallback, {
            "source": "natural_rule_fallback",
            "error": f"{type(exc).__name__}: {exc}",
            "matched_rule": matched_rule or {},
        }
    fallback, matched_rule = _fallback_collection_name_from_natural_strategy(collection_strategy, job)
    return fallback, {
        "source": "natural_rule_fallback",
        "error": "llm_returned_invalid_collection",
        "matched_rule": matched_rule or {},
    }


async def _platform_options_from_job_collection_strategy(
    collection_strategy: Any,
    job: Job,
    target_platforms: Any = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(collection_strategy, dict):
        return {}
    mode = str(collection_strategy.get("mode") or "").strip()
    if mode not in {"rule_based", "llm_classify"}:
        return {}
    if mode == "rule_based":
        collection_name, classification = _collection_name_from_rule_strategy(collection_strategy, job)
    else:
        collection_name, classification = await _collection_name_from_llm_strategy(collection_strategy, job)
        if str((classification or {}).get("source") or "").strip() != "llm":
            return {}
    if not collection_name:
        return {}
    platforms = [
        platform
        for platform in (normalize_publication_platform(item) for item in (target_platforms or []))
        if platform
    ]
    options: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        options[platform] = {
            "collection_name": collection_name,
            "platform_specific_overrides": {
                "collection_management": {
                    "status": "select_existing",
                    "target_collection_name": collection_name,
                    "selected_collection_name": collection_name,
                    "selection_source": "creator_collection_strategy",
                },
                "collection_strategy": {
                    "mode": mode,
                    "source": collection_strategy.get("source") or "creator_publication_profile",
                    "classification": classification,
                },
            },
        }
    return options


async def _job_agent_publication_profile_options(
    session: AsyncSession,
    job: Job,
    *,
    resolve_dynamic_strategy: bool = True,
) -> dict[str, dict[str, Any]]:
    result = await session.execute(
        select(JobAgentPlan)
        .where(JobAgentPlan.job_id == job.id)
    )
    plan = result.scalar_one_or_none()
    if plan is None or plan.publication_profile_id is None:
        return {}
    profile = await session.get(CreatorPublicationProfile, plan.publication_profile_id)
    if profile is None:
        return {}
    payload = profile.publication_payload_json if isinstance(profile.publication_payload_json, dict) else {}
    profile_options = _normalize_publish_platform_options_payload(payload.get("platform_options"))
    if not resolve_dynamic_strategy:
        return profile_options
    target_platforms = list(payload.get("default_platforms") or []) or list(profile_options.keys())
    strategy_options = await _platform_options_from_job_collection_strategy(
        payload.get("collection_strategy"),
        job,
        target_platforms,
    )
    return _merge_publish_platform_options(profile_options, strategy_options)


def _derive_job_publication_folder_path(job: Job, render_output: RenderOutput | None) -> str:
    candidates = [
        str(getattr(render_output, "output_path", "") or "").strip() if render_output is not None else "",
        str(getattr(job, "output_dir", "") or "").strip(),
        str(getattr(job, "source_path", "") or "").strip(),
    ]
    for raw in candidates:
        if not raw:
            continue
        if raw in {".", "./", ".\\"}:
            continue
        try:
            if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("\\\\"):
                path_like = PureWindowsPath(raw)
                return str(path_like.parent if path_like.suffix else path_like)
            path = Path(raw).expanduser()
        except Exception:
            continue
        if path.suffix:
            return str(path.parent)
        return str(path)
    return ""


def _normalize_publication_path_for_compare(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.replace("/", "\\").rstrip("\\").casefold()


def _expected_job_publication_material_dir(job: Job, render_output: RenderOutput | None) -> str:
    folder_path = _derive_job_publication_folder_path(job, render_output)
    if not folder_path:
        return ""
    return str(Path(folder_path).expanduser() / "smart-copy")


def _publication_packaging_material_dir(packaging: dict[str, Any] | None) -> str:
    if not isinstance(packaging, dict):
        return ""
    metadata = packaging.get("metadata") if isinstance(packaging.get("metadata"), dict) else {}
    candidates = [
        packaging.get("material_dir"),
        packaging.get("smart_copy_dir"),
        packaging.get("material_root"),
        packaging.get("folder_path"),
        metadata.get("material_dir"),
        metadata.get("smart_copy_dir"),
        metadata.get("material_root"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _publication_packaging_belongs_to_job_render_output(
    packaging: dict[str, Any] | None,
    *,
    job: Job,
    render_output: RenderOutput | None,
) -> bool:
    if not isinstance(packaging, dict):
        return False
    expected_material_dir = _expected_job_publication_material_dir(job, render_output)
    if not expected_material_dir:
        return True
    actual_material_dir = _publication_packaging_material_dir(packaging)
    if not actual_material_dir:
        return False
    return _normalize_publication_path_for_compare(actual_material_dir) == _normalize_publication_path_for_compare(expected_material_dir)


async def _resolve_job_publication_platform_options(
    *,
    session: AsyncSession,
    job: Job,
    render_output: RenderOutput | None,
    packaging: dict[str, Any] | None,
    creator_profile: dict[str, Any] | None,
    existing_attempts: list[dict[str, Any]],
    requested_platforms: list[str] | None,
    requested_platform_options: Any,
    resolve_dynamic_options: bool = True,
) -> dict[str, dict[str, Any]]:
    explicit_options = _normalize_publish_platform_options_payload(requested_platform_options)
    if explicit_options:
        return explicit_options
    profile_options = await _job_agent_publication_profile_options(
        session,
        job,
        resolve_dynamic_strategy=resolve_dynamic_options,
    )
    if not creator_profile:
        return profile_options
    if not resolve_dynamic_options:
        return profile_options
    base_plan = build_publication_plan(
        job=job,
        render_output=render_output,
        platform_packaging=packaging,
        creator_profile=creator_profile,
        requested_platforms=requested_platforms,
        platform_options=None,
        existing_attempts=existing_attempts,
    )
    if not list(base_plan.get("targets") or []):
        return profile_options
    folder_path = _derive_job_publication_folder_path(job, render_output)
    scheme = await generate_publication_scheme(
        plan=base_plan,
        creator_profile=creator_profile,
        folder_path=folder_path,
        browser="chrome",
        force_probe=False,
    )
    scheme_options = _normalize_publish_platform_options_payload(scheme.get("platform_options"))
    return _merge_publish_platform_options(scheme_options, profile_options)


def _dispatch_publication_worker_tick(created_count: int) -> None:
    if created_count <= 0:
        return
    try:
        celery_app.send_task(
            "roughcut.pipeline.tasks.publication_worker_tick",
            kwargs={"limit": max(1, min(20, int(created_count)))},
            queue="publication_queue",
        )
    except Exception:
        pass


def _job_publication_packaging_needs_generation(
    packaging: dict[str, Any] | None,
    *,
    requested_platforms: list[str] | None = None,
) -> bool:
    if not isinstance(packaging, dict):
        return True
    root_status = str(packaging.get("status") or "").strip().lower()
    if root_status == "failed":
        return True
    contract = packaging.get("material_contract")
    if isinstance(contract, dict) and str(contract.get("status") or "").strip().lower() == "failed":
        return True
    platforms = packaging.get("platforms")
    requested = [normalize_publication_platform(item) for item in list(requested_platforms or [])]
    requested = [item for item in requested if item]
    if isinstance(platforms, dict):
        platform_ids = {
            normalize_publication_platform(platform)
            for platform, value in platforms.items()
            if isinstance(value, dict)
        }
        if requested:
            return any(platform not in platform_ids for platform in requested)
        return bool(platform_ids) is False
    if isinstance(platforms, list):
        platform_ids = {
            normalize_publication_platform(item.get("platform"))
            for item in platforms
            if isinstance(item, dict)
        }
        if requested:
            return any(platform not in platform_ids for platform in requested)
        return bool(platform_ids) is False
    return True


async def _generate_job_publication_materials(
    *,
    job: Job,
    render_output: RenderOutput | None,
    creator_profile: dict[str, Any] | None,
    creator_profile_id: str | None,
    platforms: list[str] | None,
) -> dict[str, Any]:
    folder_path = _derive_job_publication_folder_path(job, render_output)
    if not folder_path:
        raise HTTPException(status_code=409, detail="无法定位成片目录，不能自动生成发布物料。")
    try:
        result = await generate_intelligent_copy(
            folder_path,
            platforms=platforms or None,
            creator_profile_id=creator_profile_id,
            creator_profile=creator_profile,
            creator_profile_name=str((creator_profile or {}).get("display_name") or "").strip() or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"自动生成发布物料失败：{exc}") from exc
    return {
        "status": (
            "completed"
            if bool(result.get("publish_ready") or result.get("one_click_publish_ready"))
            else str(result.get("status") or "completed")
        ),
        "source": "job_one_click_publish",
        "folder_path": folder_path,
        "material_dir": str(result.get("material_dir") or ""),
        "platform_packaging_json_path": str(result.get("platform_packaging_json_path") or ""),
        "publish_ready": bool(result.get("publish_ready") or result.get("one_click_publish_ready")),
        "blocking_reasons": [str(item).strip() for item in (result.get("blocking_reasons") or []) if str(item).strip()],
    }


def _publication_plan_cover_auto_heal_reasons(plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    candidates = [
        *[str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip()],
        *[str(item).strip() for item in (plan.get("warnings") or []) if str(item).strip()],
    ]
    reasons: list[str] = []
    for reason in candidates:
        normalized = reason.lower()
        if any(token in normalized for token in _PUBLICATION_COVER_AUTO_HEAL_BLOCK_TOKENS):
            reasons.append(reason)
    return list(dict.fromkeys(reasons))


def _attach_cover_auto_heal_status(plan: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    updated = dict(plan)
    updated["cover_auto_heal"] = status
    status_kind = str(status.get("status") or "").strip().lower()
    if status_kind in {"failed", "needs_human"}:
        blocked_reasons = [str(item).strip() for item in (updated.get("blocked_reasons") or []) if str(item).strip()]
        summary = str(status.get("summary") or "封面自愈未能恢复发布计划，需人工处理。").strip()
        if summary and summary not in blocked_reasons:
            blocked_reasons.append(summary)
        updated["blocked_reasons"] = blocked_reasons
        updated["status"] = "blocked"
        updated["publish_ready"] = False
    return updated


async def _maybe_auto_heal_job_publication_cover_plan(
    *,
    plan: dict[str, Any],
    job: Job,
    render_output: RenderOutput | None,
    packaging: dict[str, Any] | None,
    creator_profile: dict[str, Any] | None,
    creator_profile_id: str | None,
    requested_platforms: list[str] | None,
    platform_options: dict[str, Any],
    existing_attempts: list[dict[str, Any]],
    session: AsyncSession,
) -> tuple[dict[str, Any], Job, RenderOutput | None, dict[str, Any] | None, dict[str, Any] | None]:
    reasons = _publication_plan_cover_auto_heal_reasons(plan)
    if not reasons or publication_plan_is_publishable(plan):
        return plan, job, render_output, packaging, creator_profile
    settings = get_settings()
    if not bool(getattr(settings, "publication_cover_auto_heal_enabled", True)):
        return plan, job, render_output, packaging, creator_profile
    try:
        max_attempts = int(getattr(settings, "publication_cover_auto_heal_max_attempts", 1) or 1)
    except (TypeError, ValueError):
        max_attempts = 1
    max_attempts = max(0, min(3, max_attempts))
    if max_attempts <= 0:
        return plan, job, render_output, packaging, creator_profile

    folder_path = _derive_job_publication_folder_path(job, render_output)
    if not folder_path:
        return plan, job, render_output, packaging, creator_profile

    current_plan = plan
    current_job = job
    current_render_output = render_output
    current_packaging = packaging
    current_creator_profile = creator_profile
    attempts: list[dict[str, Any]] = []
    creator_profile_name = str((creator_profile or {}).get("display_name") or "").strip()
    for attempt_index in range(1, max_attempts + 1):
        before_reasons = _publication_plan_cover_auto_heal_reasons(current_plan)
        try:
            healed_result = await rerender_existing_intelligent_copy_cover_groups(
                folder_path,
                platforms=requested_platforms,
                refresh_cover_source=False,
                creator_profile_name=creator_profile_name or None,
            )
            current_job, current_render_output, current_packaging, current_creator_profile = await _load_publication_inputs(
                job_id=current_job.id,
                creator_profile_id=creator_profile_id,
                session=session,
            )
            current_plan = build_publication_plan(
                job=current_job,
                render_output=current_render_output,
                platform_packaging=current_packaging,
                creator_profile=current_creator_profile,
                requested_platforms=requested_platforms,
                platform_options=platform_options,
                existing_attempts=existing_attempts,
            )
            after_reasons = _publication_plan_cover_auto_heal_reasons(current_plan)
            healed_ready = publication_plan_is_publishable(current_plan)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "healed" if healed_ready else "still_blocked",
                    "before_reasons": before_reasons,
                    "after_reasons": after_reasons,
                    "publish_ready": bool(healed_result.get("publish_ready")) if isinstance(healed_result, dict) else None,
                    "material_contract_status": (
                        str((healed_result.get("material_contract") or {}).get("status") or "").strip()
                        if isinstance(healed_result, dict) and isinstance(healed_result.get("material_contract"), dict)
                        else ""
                    ),
                }
            )
            if healed_ready or not after_reasons:
                current_plan = _attach_cover_auto_heal_status(
                    current_plan,
                    {
                        "status": "healed" if healed_ready else "rechecked",
                        "attempts": attempts,
                        "summary": "封面质量门失败后已自动重生并重新构建发布计划。",
                    },
                )
                return current_plan, current_job, current_render_output, current_packaging, current_creator_profile
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "failed",
                    "before_reasons": before_reasons,
                    "error": str(exc),
                }
            )
            current_plan = _attach_cover_auto_heal_status(
                current_plan,
                {
                    "status": "failed",
                    "attempts": attempts,
                    "summary": f"封面自愈执行失败，需人工处理：{exc}",
                },
            )
            return current_plan, current_job, current_render_output, current_packaging, current_creator_profile

    current_plan = _attach_cover_auto_heal_status(
        current_plan,
        {
            "status": "needs_human",
            "attempts": attempts,
            "summary": f"封面自愈重试已耗尽（{max_attempts} 次），需人工处理后再发布。",
        },
    )
    return current_plan, current_job, current_render_output, current_packaging, current_creator_profile


async def _load_publication_inputs(
    *,
    job_id: uuid.UUID,
    creator_profile_id: str | None,
    session: AsyncSession,
) -> tuple[Job, RenderOutput | None, dict[str, Any] | None, dict[str, Any] | None]:
    job_result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    render_result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job_id, RenderOutput.status == "done")
        .order_by(RenderOutput.created_at.desc())
    )
    render_output = render_result.scalars().first()

    packaging_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=("platform_packaging_md",),
    )
    artifact_packaging = packaging_artifact.data_json if packaging_artifact and isinstance(packaging_artifact.data_json, dict) else None
    packaging = artifact_packaging
    if artifact_packaging is not None and not _publication_packaging_belongs_to_job_render_output(
        artifact_packaging,
        job=job,
        render_output=render_output,
    ):
        packaging = None
    smart_copy_packaging = _load_job_smart_copy_publication_packaging(job=job, render_output=render_output)
    if smart_copy_packaging is not None:
        packaging = smart_copy_packaging
    elif _job_publication_packaging_needs_generation(packaging):
        packaging = smart_copy_packaging or packaging

    creator_profile = _resolve_publication_creator_profile(creator_profile_id)
    creator_profile = await _merge_job_creator_card_publication_bindings(
        session=session,
        job=job,
        creator_profile=creator_profile,
    )
    return job, render_output, packaging, creator_profile


def _load_job_smart_copy_publication_packaging(
    *,
    job: Job,
    render_output: RenderOutput | None,
) -> dict[str, Any] | None:
    folder_path = _derive_job_publication_folder_path(job, render_output)
    if not folder_path:
        return None
    material_dir = Path(folder_path).expanduser() / "smart-copy"
    material_dir = _resolve_job_smart_copy_material_dir(material_dir) or material_dir
    packaging, _sources = load_publication_packaging_payload(
        material_json=str(resolve_smart_copy_material_json_path(material_dir)),
        platform_packaging=str(resolve_smart_copy_platform_packaging_json_path(material_dir)),
    )
    discovered_material_dir = _discover_job_smart_copy_material_dir(
        job=job,
        render_output=render_output,
        current_material_dir=material_dir,
        current_packaging=packaging if isinstance(packaging, dict) else None,
    )
    if discovered_material_dir is not None and discovered_material_dir != material_dir:
        discovered_packaging, _discovered_sources = load_publication_packaging_payload(
            material_json=str(resolve_smart_copy_material_json_path(discovered_material_dir)),
            platform_packaging=str(resolve_smart_copy_platform_packaging_json_path(discovered_material_dir)),
        )
        if _publication_packaging_platform_count(discovered_packaging) > _publication_packaging_platform_count(packaging):
            material_dir = discovered_material_dir
            packaging = discovered_packaging
    packaging = _merge_job_generation_task_publication_packaging(
        packaging if isinstance(packaging, dict) else None,
        material_dir=material_dir,
        job=job,
        render_output=render_output,
    )
    return packaging if isinstance(packaging, dict) else None


def _publication_packaging_platform_count(packaging: Any) -> int:
    platforms = packaging.get("platforms") if isinstance(packaging, dict) else None
    if isinstance(platforms, dict):
        return len(platforms)
    if isinstance(platforms, list):
        return len([item for item in platforms if isinstance(item, dict)])
    return 0


def _discover_job_smart_copy_material_dir(
    *,
    job: Job,
    render_output: RenderOutput | None,
    current_material_dir: Path,
    current_packaging: dict[str, Any] | None,
) -> Path | None:
    output_root = DEFAULT_PROJECT_ROOT / "data" / "runtime" / "output"
    if not output_root.exists():
        return None
    current_count = _publication_packaging_platform_count(current_packaging)
    query_text = " ".join(
        str(value or "")
        for value in (
            getattr(job, "source_name", ""),
            getattr(job, "task_brief", ""),
            getattr(job, "output_dir", ""),
            getattr(render_output, "output_path", "") if render_output is not None else "",
        )
    )
    query_tokens = _publication_material_discovery_tokens(query_text)
    candidates: list[tuple[int, int, float, Path]] = []
    for packaging_path in output_root.rglob("platform-packaging.json"):
        material_dir = packaging_path.parent
        if material_dir.name == "_meta":
            material_dir = material_dir.parent
        if material_dir.name != "smart-copy":
            continue
        try:
            package_payload, _sources = load_publication_packaging_payload(
                material_json=str(resolve_smart_copy_material_json_path(material_dir)),
                platform_packaging=str(resolve_smart_copy_platform_packaging_json_path(material_dir)),
            )
        except Exception:
            continue
        platform_count = _publication_packaging_platform_count(package_payload)
        if platform_count <= current_count:
            continue
        haystack = _normalize_publication_discovery_text(str(material_dir.parent))
        score = sum(1 for token in query_tokens if token in haystack)
        if score <= 0 and query_tokens:
            continue
        try:
            mtime = packaging_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((score, platform_count, mtime, material_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates[0][3]


def _normalize_publication_discovery_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("\\", "/").casefold())


def _publication_material_discovery_tokens(value: Any) -> list[str]:
    normalized = _normalize_publication_discovery_text(value)
    raw_tokens = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", normalized)
    tokens = [token for token in raw_tokens if len(token) >= 2]
    priority = [
        token
        for token in tokens
        if len(token) >= 4
    ]
    return list(dict.fromkeys(priority or tokens))


def _merge_job_generation_task_publication_packaging(
    packaging: dict[str, Any] | None,
    *,
    material_dir: Path,
    job: Job,
    render_output: RenderOutput | None,
) -> dict[str, Any] | None:
    task_packaging = _load_matching_generation_task_publication_packaging(
        material_dir=material_dir,
        job=job,
        render_output=render_output,
    )
    if task_packaging is None:
        return packaging
    if packaging is None:
        return task_packaging
    current_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    task_platforms = task_packaging.get("platforms") if isinstance(task_packaging.get("platforms"), dict) else {}
    if not task_platforms:
        return packaging
    merged = dict(packaging)
    merged_platforms = {
        **task_platforms,
        **current_platforms,
    }
    merged["platforms"] = merged_platforms
    return normalize_publication_packaging_payload(merged, material_dir=str(material_dir))


def _load_matching_generation_task_publication_packaging(
    *,
    material_dir: Path,
    job: Job,
    render_output: RenderOutput | None,
) -> dict[str, Any] | None:
    task_store = DEFAULT_PROJECT_ROOT / "data" / "intelligent_copy" / "generation_tasks.json"
    try:
        payload = json.loads(task_store.read_text(encoding="utf-8"))
    except Exception:
        return None
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        return None
    expected_keys = _job_generation_task_match_keys(job=job, render_output=render_output, material_dir=material_dir)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status") or "").strip().lower() not in {"completed", "done", "success"}:
            continue
        if not _generation_task_matches_job_material(task, expected_keys):
            continue
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        normalized = normalize_publication_packaging_payload(result, material_dir=str(material_dir))
        platforms = normalized.get("platforms") if isinstance(normalized, dict) and isinstance(normalized.get("platforms"), dict) else {}
        if platforms:
            return normalized
    return None


def _job_generation_task_match_keys(
    *,
    job: Job,
    render_output: RenderOutput | None,
    material_dir: Path,
) -> set[str]:
    values = {
        str(material_dir),
        str(material_dir.parent),
        str(getattr(job, "source_name", "") or ""),
        str(getattr(job, "output_dir", "") or ""),
        str(getattr(job, "source_path", "") or ""),
        str(getattr(render_output, "output_path", "") or "") if render_output is not None else "",
    }
    return {
        _normalize_publication_path_for_compare(value)
        for value in values
        if str(value or "").strip()
    }


def _generation_task_matches_job_material(task: dict[str, Any], expected_keys: set[str]) -> bool:
    inspection = task.get("inspection") if isinstance(task.get("inspection"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    candidates = [
        task.get("material_dir"),
        task.get("folder_path"),
        inspection.get("material_dir"),
        inspection.get("folder_path"),
        inspection.get("video_file"),
        result.get("material_dir"),
        result.get("folder_path"),
        result.get("markdown_path"),
        result.get("json_path"),
    ]
    normalized_candidates = {
        _normalize_publication_path_for_compare(candidate)
        for candidate in candidates
        if str(candidate or "").strip()
    }
    if normalized_candidates & expected_keys:
        return True
    for candidate in normalized_candidates:
        if any(key and (key in candidate or candidate in key) for key in expected_keys):
            return True
    return False


def _resolve_job_smart_copy_material_dir(material_dir: Path) -> Path | None:
    if material_dir.exists():
        return material_dir
    raw_material_dir = str(material_dir)
    if not _looks_like_host_publication_path(raw_material_dir):
        return None
    return _materialize_job_smart_copy_material_dir(raw_material_dir)


def _looks_like_host_publication_path(value: Any) -> bool:
    text = str(value or "").strip().strip('"')
    if not text:
        return False
    return text.startswith(("\\\\", "//")) or bool(re.match(r"^[A-Za-z]:[\\/]", text))


def _materialize_job_smart_copy_material_dir(raw_material_dir: str) -> Path | None:
    parent_folder = _host_smart_copy_parent_folder_path(raw_material_dir)
    if parent_folder:
        materialized_parent = _materialize_job_publication_folder(parent_folder)
        if materialized_parent is not None:
            materialized_material_dir = materialized_parent / "smart-copy"
            if resolve_smart_copy_platform_packaging_json_path(materialized_material_dir).exists():
                return materialized_material_dir

    return _materialize_job_publication_folder(raw_material_dir)


def _host_smart_copy_parent_folder_path(raw_material_dir: str) -> str:
    text = str(raw_material_dir or "").strip().strip('"')
    if not text or not _looks_like_host_publication_path(text):
        return ""
    path = PureWindowsPath(text)
    if path.name.casefold() != "smart-copy":
        return ""
    parent = str(path.parent or "").strip()
    return parent if parent and parent != "." and parent != text else ""


def _materialize_job_publication_folder(raw_folder_path: str) -> Path | None:
    url = resolve_codex_proxy_sibling_url("/v1/host/materialize-directory")
    if not url:
        return None

    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.post(
            url,
            json={
                "folder_path": str(raw_folder_path or "").strip().strip('"'),
                "container_output_root": str(os.getenv("ROUGHCUT_OUTPUT_ROOT", "/app/data") or "/app/data"),
            },
            headers=headers,
            timeout=float(os.getenv("ROUGHCUT_HOST_MATERIALIZE_TIMEOUT_SEC", "120") or "120"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    materialized_folder = str(payload.get("folder_path") or "").strip()
    if materialized_folder:
        return Path(materialized_folder).expanduser()

    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    for item in files:
        if not isinstance(item, dict):
            continue
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        normalized = path_text.replace("\\", "/").rstrip("/")
        if normalized.endswith("/_meta/platform-packaging.json"):
            return Path(path_text).expanduser().parent.parent
        if normalized.endswith("/platform-packaging.json"):
            return Path(path_text).expanduser().parent
    return None


def _resolve_publication_creator_profile(creator_profile_id: str | None) -> dict[str, Any] | None:
    profile_id = str(creator_profile_id or "").strip()
    if profile_id:
        try:
            return get_avatar_material_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Creator profile not found") from exc

    profiles = list_avatar_material_profiles()
    return next((profile for profile in profiles if active_publication_credentials(profile)), profiles[0] if profiles else None)


async def _merge_job_creator_card_publication_bindings(
    *,
    session: AsyncSession,
    job: Job,
    creator_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    base_profile = dict(creator_profile or {})
    creator = await _find_job_publication_creator_card(
        session=session,
        job=job,
        creator_profile=base_profile,
    )
    if creator is None or creator.publication_profile is None:
        return creator_profile
    credentials = _creator_publication_profile_credentials(creator.publication_profile)
    if not credentials:
        return creator_profile

    creator_payload = (
        dict(base_profile.get("creator_profile"))
        if isinstance(base_profile.get("creator_profile"), dict)
        else {}
    )
    publishing = (
        dict(creator_payload.get("publishing"))
        if isinstance(creator_payload.get("publishing"), dict)
        else {}
    )
    existing_credentials = [
        item
        for item in (publishing.get("platform_credentials") or [])
        if isinstance(item, dict)
    ]
    merged_by_platform = {
        str(item.get("platform") or "").strip().lower(): dict(item)
        for item in existing_credentials
        if str(item.get("platform") or "").strip()
    }
    for credential in credentials:
        platform = str(credential.get("platform") or "").strip().lower()
        if platform:
            merged_by_platform[platform] = credential
    publishing["platform_credentials"] = list(merged_by_platform.values())
    if "active_platforms" not in publishing:
        publishing["active_platforms"] = [item["platform"] for item in credentials if item.get("platform")]
    creator_payload["publishing"] = publishing
    base_profile["creator_profile"] = creator_payload
    if not str(base_profile.get("display_name") or "").strip():
        base_profile["display_name"] = creator.name
    base_profile["creator_card_id"] = str(creator.id)
    return base_profile


async def _find_job_publication_creator_card(
    *,
    session: AsyncSession,
    job: Job,
    creator_profile: dict[str, Any],
) -> CreatorCard | None:
    if job.creator_card_id:
        result = await session.execute(
            select(CreatorCard)
            .where(CreatorCard.id == job.creator_card_id)
            .options(selectinload(CreatorCard.publication_profile).selectinload(CreatorPublicationProfile.bindings))
        )
        creator = result.scalar_one_or_none()
        if creator is not None:
            return creator

    candidate_names = [
        str(creator_profile.get("display_name") or "").strip(),
        str(creator_profile.get("name") or "").strip(),
    ]
    compatible = creator_profile.get("creator_card_compatible")
    if isinstance(compatible, dict):
        candidate_names.append(str(compatible.get("name") or "").strip())
    for name in dict.fromkeys(item for item in candidate_names if item):
        result = await session.execute(
            select(CreatorCard)
            .where(CreatorCard.name == name)
            .options(selectinload(CreatorCard.publication_profile).selectinload(CreatorPublicationProfile.bindings))
            .limit(1)
        )
        creator = result.scalar_one_or_none()
        if creator is not None:
            return creator
    return None


def _creator_publication_profile_credentials(profile: CreatorPublicationProfile) -> list[dict[str, Any]]:
    credentials: list[dict[str, Any]] = []
    for binding in profile.bindings or []:
        payload = binding.binding_payload_json if isinstance(binding.binding_payload_json, dict) else {}
        platform = str(binding.platform or payload.get("platform") or "").strip().lower()
        credential_ref = str(binding.credential_ref or payload.get("credential_ref") or "").strip()
        if not platform or not credential_ref:
            continue
        status = str(payload.get("status") or "").strip().lower().replace("-", "_")
        if status == "login_confirmed":
            status = "logged_in"
        credentials.append(
            {
                "id": str(binding.id),
                "platform": platform,
                "credential_ref": credential_ref,
                "account_label": str(payload.get("account_label") or platform).strip(),
                "browser_profile_id": str(payload.get("browser_profile_id") or "").strip() or credential_ref,
                "browser_binding": payload.get("browser_binding") if isinstance(payload.get("browser_binding"), dict) else {},
                "status": status or "unverified",
                "enabled": bool(payload.get("enabled", True)),
                "adapter": str(payload.get("adapter") or "").strip() or ("social_auto_upload" if credential_ref.startswith("social-auto-upload:") else ""),
                "notes": str(payload.get("notes") or "").strip() or None,
            }
        )
    return credentials


async def _load_download_context(job_id: uuid.UUID, session: AsyncSession) -> tuple[RenderOutput | None, dict[str, Any]]:
    render_output = await _load_latest_done_render_output(job_id, session)
    artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=("render_outputs",),
    )
    artifact_payload = artifact.data_json if artifact and isinstance(artifact.data_json, dict) else {}
    files = _collect_downloadable_files(render_output, artifact_payload)
    if not files:
        raise HTTPException(status_code=404, detail="Rendered output not found")
    return render_output, artifact_payload


async def _load_latest_done_render_output(job_id: uuid.UUID, session: AsyncSession) -> RenderOutput | None:
    result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job_id, RenderOutput.status == "done", RenderOutput.output_path.is_not(None))
        .order_by(RenderOutput.created_at.desc())
    )
    render_output = result.scalar_one_or_none()
    if render_output is not None:
        return render_output

    fallback_result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job_id, RenderOutput.output_path.is_not(None))
        .order_by(RenderOutput.created_at.desc())
    )
    return fallback_result.scalar_one_or_none()


_DOWNLOADABLE_RENDER_KEYS: tuple[tuple[str, str, str, bool], ...] = (
    ("packaged_mp4", "成片（包装版）", "video", True),
    ("plain_mp4", "成片（素版）", "video", True),
    ("avatar_mp4", "成片（数字人）", "video", True),
    ("ai_effect_mp4", "成片（AI 效果）", "video", True),
    ("packaged_srt", "字幕（包装版）", "subtitle", True),
    ("plain_srt", "字幕（素版）", "subtitle", True),
    ("avatar_srt", "字幕（数字人）", "subtitle", True),
    ("ai_effect_srt", "字幕（AI 效果）", "subtitle", True),
    ("cover", "封面", "image", True),
)


def _collect_downloadable_files(render_output: RenderOutput | None, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = payload if isinstance(payload, dict) else {}
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_file(file_id: str, label: str, kind: str, value: Any, *, recommended: bool = True) -> None:
        path_text = str(value or "").strip()
        if not path_text:
            return
        path = _first_existing_runtime_path(path_text, file_only=True)
        if path is None:
            return
        resolved = str(path)
        if resolved in seen_paths:
            return
        seen_paths.add(resolved)
        files.append(
            {
                "id": file_id,
                "label": label,
                "filename": path.name,
                "kind": kind,
                "size_bytes": int(path.stat().st_size),
                "recommended": recommended,
                "_path": str(path),
            }
        )

    for key, label, kind, recommended in _DOWNLOADABLE_RENDER_KEYS:
        add_file(key, label, kind, payload.get(key), recommended=recommended)

    for index, value in enumerate(payload.get("cover_variants") or []):
        add_file(f"cover_variants:{index}", f"封面备选 {index + 1}", "image", value, recommended=False)

    if render_output is not None and not any(item["id"] == "packaged_mp4" for item in files):
        add_file("packaged_mp4", "成片（包装版）", "video", render_output.output_path, recommended=True)

    files.sort(key=lambda item: _download_file_sort_key(str(item["id"])))
    return files


def _download_file_sort_key(file_id: str) -> tuple[int, str]:
    priority = {
        "packaged_mp4": 0,
        "avatar_mp4": 1,
        "ai_effect_mp4": 2,
        "plain_mp4": 3,
        "packaged_srt": 4,
        "avatar_srt": 5,
        "ai_effect_srt": 6,
        "plain_srt": 7,
        "cover": 8,
    }
    if file_id.startswith("cover_variants:"):
        return (9, file_id)
    return (priority.get(file_id, 99), file_id)


def _sanitize_download_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._- ")
    return cleaned[:80] or "roughcut"


def _unique_zip_member_name(filename: str, used_names: set[str]) -> str:
    safe_name = _sanitize_download_filename(Path(filename).stem)
    suffix = Path(filename).suffix
    candidate = f"{safe_name}{suffix}"
    index = 2
    while candidate in used_names:
        candidate = f"{safe_name}_{index}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _resolve_download_variant_path(render_output: RenderOutput | None, payload: dict[str, Any] | None, variant: str) -> Path:
    payload = payload if isinstance(payload, dict) else {}
    if variant == "packaged":
        path = _first_existing_download_path(payload.get("packaged_mp4"), render_output.output_path if render_output else None)
        if path is not None:
            return path
        raise HTTPException(status_code=404, detail="Rendered output file not found")

    plain_path = _first_existing_download_path(payload.get("plain_mp4"))
    if plain_path is not None:
        return plain_path

    base_output = _first_existing_download_path(payload.get("packaged_mp4"), render_output.output_path if render_output else None)
    if base_output is None:
        raise HTTPException(status_code=404, detail="Rendered output file not found")

    candidate_names = [
        base_output.name.replace("成片", "素板"),
        base_output.name.replace("成片", "素版"),
        base_output.name.replace("packaged", "plain"),
    ]
    for candidate_name in candidate_names:
        candidate = base_output.with_name(candidate_name)
        if candidate.exists():
            return candidate

    raise HTTPException(status_code=404, detail="Plain rendered output not found")


def _first_existing_download_path(*values: Any) -> Path | None:
    for value in values:
        path_text = str(value or "").strip()
        if not path_text:
            continue
        path = _first_existing_runtime_path(path_text, file_only=True)
        if path is not None:
            return path
    return None


def _first_existing_runtime_path(value: Any, *, file_only: bool) -> Path | None:
    for path in _runtime_path_candidates(value):
        try:
            if path.exists() and (path.is_file() if file_only else True):
                return path.resolve()
        except OSError:
            continue
    return None


def _runtime_path_candidates(value: Any) -> list[Path]:
    path_text = str(value or "").strip().strip('"')
    if not path_text:
        return []

    candidates: list[Path] = []

    def add(candidate: Path) -> None:
        key = str(candidate)
        if key not in {str(item) for item in candidates}:
            candidates.append(candidate)

    add(Path(path_text).expanduser())

    for candidate in _container_paths_for_host_runtime_path(path_text):
        add(candidate)
    for candidate in _host_paths_for_container_runtime_path(path_text):
        add(candidate)

    raw_candidate = Path(path_text).expanduser()
    if not raw_candidate.is_absolute() and not _looks_like_windows_host_path(path_text):
        for base in _runtime_relative_path_bases():
            add((base / raw_candidate).expanduser())

    return candidates


def _container_paths_for_host_runtime_path(path_text: str) -> list[Path]:
    relative_parts = _relative_parts_for_windows_roots(path_text, _runtime_host_root_texts())
    if not relative_parts:
        return []
    return [root.joinpath(*relative_parts) for root in _runtime_container_roots()]


def _host_paths_for_container_runtime_path(path_text: str) -> list[Path]:
    normalized = str(path_text or "").strip().replace("\\", "/")
    if not normalized:
        return []
    for root in _runtime_container_roots():
        root_text = str(root).replace("\\", "/").rstrip("/")
        prefix = f"{root_text}/"
        if normalized == root_text:
            relative_parts: tuple[str, ...] = ()
        elif normalized.startswith(prefix):
            relative_parts = tuple(part for part in normalized[len(prefix):].split("/") if part)
        else:
            continue
        return [Path(host_root).joinpath(*relative_parts) for host_root in _runtime_host_root_texts()]
    return []


def _relative_parts_for_windows_roots(path_text: str, roots: list[str]) -> tuple[str, ...] | None:
    normalized_path = str(path_text or "").strip().replace("/", "\\")
    if not _looks_like_windows_host_path(normalized_path):
        return None
    path_parts = PureWindowsPath(normalized_path).parts
    path_parts_key = tuple(part.casefold() for part in path_parts)
    for root in roots:
        root_text = str(root or "").strip().replace("/", "\\")
        if not root_text:
            continue
        root_parts = PureWindowsPath(root_text).parts
        root_parts_key = tuple(part.casefold() for part in root_parts)
        if len(path_parts_key) < len(root_parts_key):
            continue
        if path_parts_key[:len(root_parts_key)] == root_parts_key:
            return tuple(path_parts[len(root_parts):])
    return None


def _looks_like_windows_host_path(raw_path: str) -> bool:
    normalized = str(raw_path or "").strip()
    if normalized.startswith(("\\\\", "//")):
        return True
    return len(normalized) >= 3 and normalized[1:3] in {":\\", ":/"}


def _runtime_container_roots() -> list[Path]:
    roots: list[Path] = []
    settings = get_settings()
    for raw in (
        os.getenv("ROUGHCUT_OUTPUT_ROOT"),
        getattr(settings, "output_root", None),
        "/app/data",
        DEFAULT_PROJECT_ROOT / "data" / "runtime",
    ):
        if not raw:
            continue
        root = Path(str(raw)).expanduser()
        if str(root) not in {str(item) for item in roots}:
            roots.append(root)
    return roots


def _runtime_host_root_texts() -> list[str]:
    roots: list[str] = []
    for raw in (
        os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT"),
        os.getenv("ROUGHCUT_OUTPUT_ROOT") if os.name == "nt" else None,
        str(DEFAULT_PROJECT_ROOT / "data" / "runtime"),
    ):
        text = str(raw or "").strip()
        if text and text not in roots:
            roots.append(text)
    return roots


def _runtime_relative_path_bases() -> list[Path]:
    settings = get_settings()
    bases: list[Path] = [DEFAULT_PROJECT_ROOT]
    for raw in (
        getattr(settings, "output_root", None),
        getattr(settings, "output_dir", None),
        Path(str(getattr(settings, "output_dir", "") or "")).parent if getattr(settings, "output_dir", None) else None,
        getattr(settings, "job_storage_dir", None),
        Path(str(getattr(settings, "job_storage_dir", "") or "")).parent if getattr(settings, "job_storage_dir", None) else None,
    ):
        if not raw:
            continue
        base = Path(str(raw)).expanduser()
        if str(base) not in {str(item) for item in bases}:
            bases.append(base)
    return bases


def _revoke_running_steps(steps: list[JobStep]) -> None:
    for step in steps:
        if step.status != "running":
            continue
        task_id = (step.metadata_ or {}).get("task_id")
        if not task_id:
            continue
        try:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass


async def _clear_job_runtime_state(job_id: uuid.UUID, session: AsyncSession, *, source_path: str = "") -> None:
    packaging_artifacts = await session.execute(
        select(Artifact).where(Artifact.job_id == job_id)
    )
    render_outputs = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_id))
    artifact_rows = packaging_artifacts.scalars().all()
    render_output_rows = render_outputs.scalars().all()
    cleanup_job_runtime_files(
        str(job_id),
        artifacts=artifact_rows,
        render_outputs=render_output_rows,
        purge_deliverables=True,
        preserve_storage_keys=[source_path] if source_path else [],
    )
    _clear_content_profile_thumbnail_cache(job_id)
    _invalidate_job_file_response_cache(job_id)

    await session.execute(
        delete(FactEvidence).where(FactEvidence.claim_id.in_(select(FactClaim.id).where(FactClaim.job_id == job_id)))
    )
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(ReviewAction).where(ReviewAction.job_id == job_id))
    await session.execute(delete(RenderOutput).where(RenderOutput.job_id == job_id))
    await session.execute(delete(Timeline).where(Timeline.job_id == job_id))
    await session.execute(delete(Artifact).where(Artifact.job_id == job_id))
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job_id))


@router.post("/{job_id}/review/apply")
async def apply_review(
    job_id: uuid.UUID,
    request: ReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    touch_runtime_refresh_hold(reason="review_apply", job_id=str(job_id), hold_seconds=90)

    applied = 0
    for action in request.actions:
        # Record review action
        review = ReviewAction(
            job_id=job_id,
            target_type=action.target_type,
            target_id=action.target_id,
            action=action.action,
            override_text=action.override_text,
        )
        session.add(review)

        # Apply to subtitle correction if applicable
        if action.target_type == "subtitle_correction":
            correction = await session.get(SubtitleCorrection, action.target_id)
            if correction and correction.job_id == job_id:
                correction.human_decision = action.action
                if action.override_text:
                    correction.human_override = action.override_text
                if action.action == "accepted":
                    await _persist_reviewed_glossary_term(
                        session,
                        job=job,
                        correction=correction,
                    )
                applied += 1

    await session.commit()
    return {"applied": applied}


@router.post("/{job_id}/final-review", response_model=FinalReviewDecisionOut)
async def apply_final_review_decision(
    job_id: uuid.UUID,
    request: FinalReviewDecisionIn,
    session: AsyncSession = Depends(get_session),
):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    review_step = next((step for step in job.steps or [] if step.step_name == "final_review"), None)
    if review_step is None:
        raise HTTPException(status_code=404, detail="Final review step not found")

    decision = str(request.decision or "").strip().lower()
    note = str(request.note or "").strip() or None
    if decision == "reject" and not note:
        raise HTTPException(status_code=400, detail="note is required when decision is reject")
    if decision == "approve" and review_step.status == "done":
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="approve",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=False,
            note=note,
        )
    if review_step.status == "done" and decision == "reject":
        raise HTTPException(status_code=409, detail="Final review has already been approved")

    now = datetime.now(timezone.utc)
    session.add(
        ReviewAction(
            job_id=job.id,
            target_type="final_review",
            target_id=job.id,
            action=decision,
            override_text=note,
        )
    )

    if decision == "approve":
        mark_final_review_approved(
            review_step=review_step,
            job=job,
            now=now,
            approved_via="web",
        )
        await session.commit()
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="approve",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=False,
            note=note,
        )
    rerun_triggered = False

    from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun

    rerun_plan = combine_final_review_rerun_plans(build_final_review_rerun_plans(note))
    if rerun_plan is not None:
        review_user_feedback = extract_final_review_content_profile_feedback(note)
        steps = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.id.asc())
            )
        ).scalars().all()
        await _reset_job_for_quality_rerun(
            session,
            job,
            steps,
            rerun_steps=list(rerun_plan.rerun_steps),
            issue_codes=[f"manual_review:{rerun_plan.category}"],
        )
        first_step = next((step for step in steps if step.step_name == rerun_plan.trigger_step), None)
        apply_final_review_rerun_metadata(
            first_step=first_step,
            rerun_plan=rerun_plan,
            note=note,
            now=now,
            review_user_feedback=review_user_feedback,
        )
        rerun_triggered = True
        await session.commit()
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="reject",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=rerun_triggered,
            note=note,
        )
    mark_final_review_pending(
        review_step=review_step,
        job=job,
        now=now,
        detail="已收到成片修改意见，任务保持暂停，等待人工处理后再继续。",
        note=note,
        via="web",
    )
    await session.commit()
    return FinalReviewDecisionOut(
        job_id=str(job.id),
        decision="reject",
        job_status=str(job.status),
        review_step_status=str(review_step.status),
        rerun_triggered=rerun_triggered,
        note=note,
    )


@router.post("/{job_id}/final-review/rerender-variant-timeline", response_model=FinalReviewVariantTimelineRerenderOut)
async def rerender_final_review_variant_timeline(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    artifacts = (
        await session.execute(
            select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
    ).scalars().all()
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()] if isinstance(validation, dict) else []
    validation_status = str(validation.get("status") or "").strip().lower() if isinstance(validation, dict) else None
    if not issues or validation_status not in {"warning", "error"}:
        raise HTTPException(status_code=409, detail="No variant timeline warning detected for this job")

    steps = list(job.steps or [])
    if not steps:
        raise HTTPException(status_code=409, detail="Job steps are missing")

    rerun_steps = ["render"]

    from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun

    await _reset_job_for_quality_rerun(
        session,
        job,
        steps,
        rerun_steps=rerun_steps,
        issue_codes=["variant_timeline_warning"],
    )

    now = datetime.now(timezone.utc)
    render_step = next((step for step in steps if step.step_name == "render"), None)
    if render_step is not None:
        metadata = dict(render_step.metadata_ or {})
        metadata.update(
            {
                "detail": "时间轴对齐告警触发重渲染：render",
                "updated_at": now.isoformat(),
                "variant_timeline_validation_status": validation_status,
                "variant_timeline_validation_issues": issues[:10],
            }
        )
        render_step.metadata_ = metadata

    session.add(
        ReviewAction(
            job_id=job.id,
            target_type="final_review",
            target_id=job.id,
            action="rerender_variant_timeline",
            override_text="时间轴对齐告警触发重渲染",
        )
    )
    await session.commit()
    return FinalReviewVariantTimelineRerenderOut(
        job_id=str(job.id),
        job_status=str(job.status),
        rerun_steps=rerun_steps,
        validation_status=validation_status,
        validation_issue_count=len(issues),
    )


async def _persist_reviewed_glossary_term(
    session: AsyncSession,
    *,
    job: Job,
    correction: SubtitleCorrection,
) -> None:
    suggested = str(correction.human_override or correction.suggested_span or "").strip()
    original = str(correction.original_span or "").strip()
    if not suggested or not original or suggested == original:
        return

    profile_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=_CONTENT_PROFILE_ARTIFACT_TYPES,
    )
    content_profile = {}
    if profile_artifact and isinstance(profile_artifact.data_json, dict):
        content_profile = dict(profile_artifact.data_json)

    detected_domains = detect_glossary_domains(
        workflow_template=job.workflow_template,
        content_profile=content_profile,
    )
    scopes: list[tuple[str, str]] = []
    for domain in detected_domains:
        pair = ("domain", domain)
        if pair not in scopes:
            scopes.append(pair)

    for scope_type, scope_value in scopes:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.scope_type == scope_type,
                GlossaryTerm.scope_value == scope_value,
                GlossaryTerm.correct_form == suggested,
            )
        )
        term = result.scalar_one_or_none()
        if term is None:
            session.add(
                GlossaryTerm(
                    scope_type=scope_type,
                    scope_value=scope_value,
                    wrong_forms=[original],
                    correct_form=suggested,
                    category=correction.change_type,
                    context_hint=f"reviewed_from_job:{job.workflow_template or 'auto'}",
                )
            )
            continue
        wrong_forms = [str(item or "").strip() for item in (term.wrong_forms or []) if str(item or "").strip()]
        if original not in wrong_forms and original != suggested:
            wrong_forms.append(original)
            term.wrong_forms = wrong_forms


def _normalize_review_glossary_value(value: Any, *, max_length: int = 64) -> str:
    return " ".join(str(value or "").strip().split())[:max_length]


def _is_generic_review_hotword(value: str) -> bool:
    normalized = _normalize_review_glossary_value(value, max_length=64)
    lowered = normalized.lower()
    return lowered in {
        "",
        "unknown",
        "待确认",
        "未确认",
        "产品",
        "开箱产品",
        "主体",
        "视频主题",
        "内容主题",
    }


def _should_persist_review_alias(original: Any, corrected: Any) -> bool:
    original_text = _normalize_review_glossary_value(original, max_length=48)
    corrected_text = _normalize_review_glossary_value(corrected, max_length=48)
    if not original_text or not corrected_text or original_text == corrected_text:
        return False
    if model_numbers_conflict(original_text, corrected_text):
        return False
    if _is_generic_review_hotword(original_text) or _is_generic_review_hotword(corrected_text):
        return False
    return True


def _should_persist_review_hotword(value: Any, *, allow_phrase: bool = False) -> bool:
    text = _normalize_review_glossary_value(value, max_length=64 if allow_phrase else 48)
    if not text or _is_generic_review_hotword(text):
        return False
    if "\n" in text or "\r" in text:
        return False
    if not allow_phrase and len(text) < 2:
        return False
    if allow_phrase and len(text) < 2:
        return False
    return True


def _extract_confirmed_content_profile_alias_rows(final_profile: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    if not isinstance(final_profile, dict):
        return []
    identity_review = final_profile.get("identity_review")
    if not isinstance(identity_review, dict):
        return []
    evidence_bundle = identity_review.get("evidence_bundle")
    if not isinstance(evidence_bundle, dict):
        return []
    matched_glossary_aliases = evidence_bundle.get("matched_glossary_aliases")
    if not isinstance(matched_glossary_aliases, dict):
        return []

    rows: list[tuple[str, str, str]] = []
    field_specs = (
        ("subject_brand", "brand", "candidate_brand"),
        ("subject_model", "model", "candidate_model"),
    )
    for field_name, alias_key, candidate_key in field_specs:
        final_value = _normalize_review_glossary_value((final_profile or {}).get(field_name), max_length=48)
        candidate_value = _normalize_review_glossary_value(evidence_bundle.get(candidate_key), max_length=48)
        if not final_value or not candidate_value or final_value != candidate_value:
            continue
        for alias in matched_glossary_aliases.get(alias_key) or []:
            alias_value = _normalize_review_glossary_value(alias, max_length=48)
            if _should_persist_review_alias(alias_value, final_value):
                rows.append((field_name, alias_value, final_value))
    return rows


def _resolve_content_profile_glossary_scopes(
    *,
    job: Job,
    content_profile: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    detected_domains = detect_glossary_domains(
        workflow_template=job.workflow_template,
        content_profile=content_profile or {},
    )
    scopes: list[tuple[str, str]] = []
    for domain in detected_domains:
        pair = ("domain", domain)
        if pair not in scopes:
            scopes.append(pair)
    return scopes


async def _upsert_review_glossary_term(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_value: str,
    correct_form: str,
    wrong_form: str | None = None,
    category: str | None = None,
    context_hint: str | None = None,
) -> None:
    normalized_correct = _normalize_review_glossary_value(correct_form, max_length=64)
    normalized_wrong = _normalize_review_glossary_value(wrong_form, max_length=48) if wrong_form else ""
    conflicting_model_alias = bool(
        normalized_wrong and model_numbers_conflict(normalized_wrong, normalized_correct)
    )
    if not normalized_correct:
        return

    result = await session.execute(
        select(GlossaryTerm).where(
            GlossaryTerm.scope_type == scope_type,
            GlossaryTerm.scope_value == scope_value,
            GlossaryTerm.correct_form == normalized_correct,
        )
    )
    term = result.scalar_one_or_none()
    if term is None:
        wrong_forms = (
            [normalized_wrong]
            if normalized_wrong and normalized_wrong != normalized_correct and not conflicting_model_alias
            else []
        )
        session.add(
            GlossaryTerm(
                scope_type=scope_type,
                scope_value=scope_value,
                wrong_forms=wrong_forms,
                correct_form=normalized_correct,
                category=category,
                context_hint=context_hint,
            )
        )
        return

    wrong_forms = [str(item or "").strip() for item in (term.wrong_forms or []) if str(item or "").strip()]
    if (
        normalized_wrong
        and normalized_wrong != normalized_correct
        and not conflicting_model_alias
        and normalized_wrong not in wrong_forms
    ):
        wrong_forms.append(normalized_wrong)
        term.wrong_forms = wrong_forms
    if not term.category and category:
        term.category = category
    if not term.context_hint and context_hint:
        term.context_hint = context_hint


async def _persist_confirmed_content_profile_glossary_terms(
    session: AsyncSession,
    *,
    job: Job,
    draft_profile: dict[str, Any] | None,
    final_profile: dict[str, Any] | None,
    user_feedback: dict[str, Any] | None,
    context_hint: str | None = None,
) -> None:
    scopes = _resolve_content_profile_glossary_scopes(job=job, content_profile=final_profile)
    if not scopes:
        return

    draft_payload = draft_profile if isinstance(draft_profile, dict) else {}
    final_payload = final_profile if isinstance(final_profile, dict) else {}
    feedback_payload = user_feedback if isinstance(user_feedback, dict) else {}
    resolved_context_hint = context_hint or f"manual_content_profile_review:{job.workflow_template or 'auto'}"

    alias_rows: list[tuple[str, str, str, str]] = []
    for field_name, category in (("subject_brand", "brand"), ("subject_model", "model")):
        original_value = _normalize_review_glossary_value(draft_payload.get(field_name), max_length=48)
        corrected_value = _normalize_review_glossary_value(final_payload.get(field_name), max_length=48)
        if _should_persist_review_alias(original_value, corrected_value):
            alias_rows.append((field_name, original_value, corrected_value, category))

    for field_name, alias_value, canonical_value in _extract_confirmed_content_profile_alias_rows(final_payload):
        category = "brand" if field_name == "subject_brand" else "model"
        if _should_persist_review_alias(alias_value, canonical_value):
            alias_rows.append((field_name, alias_value, canonical_value, category))

    seen_alias_pairs: set[tuple[str, str, str]] = set()
    for field_name, wrong_value, correct_value, category in alias_rows:
        key = (field_name, wrong_value, correct_value)
        if key in seen_alias_pairs:
            continue
        seen_alias_pairs.add(key)
        for scope_type, scope_value in scopes:
            await _upsert_review_glossary_term(
                session,
                scope_type=scope_type,
                scope_value=scope_value,
                correct_form=correct_value,
                wrong_form=wrong_value,
                category=category,
                context_hint=resolved_context_hint,
            )

    canonical_terms: list[tuple[str, str]] = []
    for field_name, category in (
        ("subject_brand", "brand"),
        ("subject_model", "model"),
        ("subject_type", "subject_type"),
    ):
        value = _normalize_review_glossary_value(final_payload.get(field_name), max_length=48)
        if _should_persist_review_hotword(value):
            canonical_terms.append((value, category))

    keywords = feedback_payload.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = final_payload.get("search_queries") or []
    normalized_keywords = normalize_query_list(
        [_normalize_review_glossary_value(item, max_length=64) for item in keywords if str(item or "").strip()]
    )
    for keyword in normalized_keywords:
        if _should_persist_review_hotword(keyword, allow_phrase=True):
            canonical_terms.append((keyword, "hotword"))

    seen_terms: set[tuple[str, str]] = set()
    for correct_value, category in canonical_terms:
        key = (correct_value, category)
        if key in seen_terms:
            continue
        seen_terms.add(key)
        for scope_type, scope_value in scopes:
            await _upsert_review_glossary_term(
                session,
                scope_type=scope_type,
                scope_value=scope_value,
                correct_form=correct_value,
                category=category,
                context_hint=resolved_context_hint,
            )


@router.get("/{job_id}/activity", response_model=JobActivityOut)
async def get_job_activity(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(
                [
                    "media_meta",
                    "content_profile_draft",
                    "content_profile_final",
                    "content_profile",
                    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
                    ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
                    ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
                    "dialogue_polish_plan",
                    "ai_director_plan",
                    "avatar_commentary_plan",
                    "render_outputs",
                    "platform_packaging_md",
                    STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE,
                    QUALITY_ARTIFACT_TYPE,
                ]
            ),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()
    set_committed_value(job, "artifacts", artifacts)
    _attach_job_preview(job, lightweight=True)

    timeline_result = await session.execute(
        select(Timeline).where(
            Timeline.job_id == job_id,
            Timeline.timeline_type.in_(["editorial", "render_plan"]),
        )
    )
    timelines = timeline_result.scalars().all()

    render_result = await session.execute(
        select(RenderOutput).where(RenderOutput.job_id == job_id).order_by(RenderOutput.created_at.desc())
    )
    render_output = render_result.scalars().first()

    correction_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
    corrections = correction_result.scalars().all()
    review_action_result = await session.execute(
        select(ReviewAction).where(ReviewAction.job_id == job_id).order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
    )
    review_actions = review_action_result.scalars().all()

    current_step = _build_current_step(job)
    decisions = _build_activity_decisions(artifacts, timelines, corrections, render_output)
    events = _build_activity_events(job.steps or [], artifacts, timelines, render_output, job=job, review_actions=review_actions)

    render_payload = None
    if render_output is not None:
        render_payload = {
            "status": render_output.status,
            "progress": float(render_output.progress or 0.0),
            "output_path": render_output.output_path,
            "updated_at": _iso_or_none(render_output.created_at),
        }

    return JobActivityOut(
        job_id=str(job.id),
        status=job.status,
        review_step=job.review_step,
        review_detail=job.review_detail,
        current_step=current_step,
        render=render_payload,
        decisions=decisions,
        events=events,
    )


@router.get("/{job_id}/token-usage", response_model=TokenUsageReportOut)
async def get_job_token_usage(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    report = build_job_token_report(job.steps or [], step_labels=STEP_LABELS)
    return TokenUsageReportOut(
        job_id=str(job.id),
        has_telemetry=bool(report.get("has_telemetry")),
        total_calls=int(report.get("total_calls") or 0),
        total_prompt_tokens=int(report.get("total_prompt_tokens") or 0),
        total_completion_tokens=int(report.get("total_completion_tokens") or 0),
        total_tokens=int(report.get("total_tokens") or 0),
        steps=list(report.get("steps") or []),
        models=list(report.get("models") or []),
        cache=dict(report.get("cache") or {}),
    )


def _build_current_step(job: Job) -> dict | None:
    steps = _ordered_steps(job.steps or [])
    running = next((step for step in steps if step.status == "running"), None)
    if running:
        meta = running.metadata_ or {}
        worker_active = _step_has_worker_started(running)
        display_status = "running" if worker_active else "queued"
        base_detail = meta.get("detail")
        if not worker_active:
            queue_name = str(meta.get("queue") or "").strip()
            base_detail = base_detail or (
                f"已派发到 {queue_name}，等待 worker 接收。" if queue_name else "已派发，等待 worker 接收。"
            )
        detail = _decorate_step_detail(
            base_detail,
            _step_elapsed_seconds(running),
            running=worker_active,
        )
        return {
            "step_name": running.step_name,
            "label": STEP_LABELS.get(running.step_name, running.step_name),
            "status": display_status,
            "detail": detail,
            "progress": meta.get("progress"),
            "updated_at": meta.get("updated_at") or _iso_or_none(running.started_at),
        }

    if job.status in {"failed", "cancelled"}:
        terminal_statuses = {"failed", "cancelled"}
        failed_step = _latest_terminal_step(steps, statuses=terminal_statuses)
        if failed_step is not None:
            return {
                "step_name": failed_step.step_name,
                "label": STEP_LABELS.get(failed_step.step_name, failed_step.step_name),
                "status": failed_step.status,
                "detail": _coalesce_step_error_detail(
                    failed_step,
                    fallback=job.error_message,
                ),
                "progress": None,
                "updated_at": _iso_or_none(failed_step.finished_at or failed_step.started_at or job.updated_at),
            }
        return {
            "step_name": steps[0].step_name if steps else "系统",
            "label": STEP_LABELS.get(steps[0].step_name, "任务") if steps else "任务",
            "status": job.status,
            "detail": job.error_message or "任务已结束但未产生可追踪步骤记录",
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    if job.status == "needs_review":
        review_context = _resolve_job_review_context(job)
        if review_context["step_name"] is not None:
            return {
                "step_name": review_context["step_name"],
                "label": review_context["label"],
                "status": "needs_review",
                "detail": review_context["detail"],
                "progress": None,
                "updated_at": _iso_or_none(job.updated_at),
            }
        return {
            "step_name": "summary_review",
            "label": STEP_LABELS["summary_review"],
            "status": "needs_review",
            "detail": _review_step_waiting_detail("summary_review"),
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    if job.status == "awaiting_manual_edit":
        waiting_context = _resolve_manual_editor_waiting_context(job)
        return {
            "step_name": waiting_context["step_name"],
            "label": waiting_context["label"],
            "status": "pending",
            "detail": waiting_context["detail"],
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    next_pending = next((step for step in steps if step.status == "pending"), None)
    if next_pending:
        meta = next_pending.metadata_ or {}
        detail = _pending_step_transition_detail(meta.get("detail"), next_pending, steps)
        return {
            "step_name": next_pending.step_name,
            "label": STEP_LABELS.get(next_pending.step_name, next_pending.step_name),
            "status": next_pending.status,
            "detail": detail,
            "progress": None,
            "updated_at": meta.get("updated_at") or _iso_or_none(job.updated_at),
        }

    return None


def _build_activity_decisions(
    artifacts: list[Artifact],
    timelines: list[Timeline],
    corrections: list[SubtitleCorrection],
    render_output: RenderOutput | None,
) -> list[dict]:
    decisions: list[dict] = []
    render_outputs_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "render_outputs"), None)
    render_outputs = render_outputs_artifact.data_json if render_outputs_artifact and render_outputs_artifact.data_json else {}
    subtitle_quality_artifact = next(
        (
            artifact
            for artifact in reversed(artifacts)
            if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT and isinstance(artifact.data_json, dict)
        ),
        None,
    )
    subtitle_term_resolution_artifact = next(
        (
            artifact
            for artifact in reversed(artifacts)
            if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH and isinstance(artifact.data_json, dict)
        ),
        None,
    )
    subtitle_consistency_artifact = next(
        (
            artifact
            for artifact in reversed(artifacts)
            if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT and isinstance(artifact.data_json, dict)
        ),
        None,
    )

    profile = _select_preferred_content_profile_artifact([
        artifact
        for artifact in artifacts
        if artifact.artifact_type in {"content_profile", "content_profile_final", "content_profile_draft"}
    ])
    if profile and profile.data_json:
        data = profile.data_json
        subject = " · ".join(
            part for part in [data.get("subject_type"), data.get("video_theme")] if part
        ).strip() or "已生成视频类型识别"
        detail = "；".join(
            part for part in [
                f"模板：{data.get('workflow_template')}" if data.get("workflow_template") else "",
                f"摘要：{data.get('summary')}" if data.get("summary") else "",
            ] if part
        ) or None
        decisions.append(
            {
                "kind": "content_profile",
                "step_name": "content_profile",
                "title": "内容识别",
                "status": "done" if profile.artifact_type != "content_profile_draft" else "needs_review",
                "summary": subject,
                "detail": detail,
                "updated_at": _iso_or_none(profile.created_at),
            }
        )

    if subtitle_quality_artifact and subtitle_quality_artifact.data_json:
        data = subtitle_quality_artifact.data_json
        score_raw = data.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        blocking = bool(data.get("blocking"))
        blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
        warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
        action_payload = build_subtitle_quality_action(data)
        quality_status = "needs_review" if bool(action_payload.get("blocking")) else "done"
        decisions.append(
            {
                "kind": "subtitle_quality",
                "step_name": "subtitle_postprocess",
                "title": "字幕阶段验收",
                "status": quality_status,
                "summary": (
                    f"字幕质检 {score:.1f} 分"
                    if score is not None
                    else ("字幕质检未通过" if blocking else "字幕质检通过")
                ),
                "detail": "；".join(blocking_reasons or warning_reasons) or None,
                "updated_at": _iso_or_none(subtitle_quality_artifact.created_at),
                **action_payload,
            }
        )

    if subtitle_term_resolution_artifact and subtitle_term_resolution_artifact.data_json:
        data = subtitle_term_resolution_artifact.data_json
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        patch_count = int(metrics.get("patch_count") or 0)
        pending = int(metrics.get("pending_count") or 0)
        auto_applied = int(metrics.get("auto_applied_count") or 0)
        autocorrect_policy = str(data.get("autocorrect_policy") or "lexical_only")
        action_payload = build_subtitle_term_resolution_action(data)
        decisions.append(
            {
                "kind": "subtitle_term_resolution",
                "step_name": "subtitle_term_resolution",
                "title": "字幕术语解析",
                "status": "needs_review" if pending > 0 else "done",
                "summary": f"识别出 {patch_count} 条术语纠偏 patch",
                "detail": f"待确认 {pending} 条，词级自动接受 {auto_applied} 条，策略 {autocorrect_policy}",
                "updated_at": _iso_or_none(subtitle_term_resolution_artifact.created_at),
                **action_payload,
            }
        )

    if subtitle_consistency_artifact and subtitle_consistency_artifact.data_json:
        data = subtitle_consistency_artifact.data_json
        score_raw = data.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        blocking = bool(data.get("blocking"))
        blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
        warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
        action_payload = build_subtitle_consistency_action(data)
        decisions.append(
            {
                "kind": "subtitle_consistency_review",
                "step_name": "subtitle_consistency_review",
                "title": "字幕一致性审校",
                "status": "needs_review" if blocking else "done",
                "summary": f"一致性得分 {score:.1f}" if score is not None else ("一致性未通过" if blocking else "一致性通过"),
                "detail": "；".join(blocking_reasons or warning_reasons) or None,
                "updated_at": _iso_or_none(subtitle_consistency_artifact.created_at),
                **action_payload,
            }
        )

    if corrections:
        accepted = sum(1 for item in corrections if item.auto_applied or item.human_decision == "accepted")
        pending = sum(1 for item in corrections if item.human_decision not in {"accepted", "rejected"})
        action_payload = build_subtitle_candidate_action(pending_count=pending)
        decisions.append(
            {
                "kind": "subtitle_review",
                "step_name": "glossary_review",
                "title": "字幕与术语",
                "status": "needs_review" if pending > 0 else "done",
                "summary": f"识别出 {len(corrections)} 处术语/字幕纠错候选",
                "detail": f"待审 {pending} 条，词级自动/已接受 {accepted} 条",
                "updated_at": _iso_or_none(max((item.created_at for item in corrections), default=None)),
                **action_payload,
            }
        )

    editorial = next((timeline for timeline in timelines if timeline.timeline_type == "editorial"), None)
    if editorial and editorial.data_json:
        cut_segments = editorial_cut_segments(editorial.data_json)
        total_cut = sum(float(segment.get("end", 0) or 0) - float(segment.get("start", 0) or 0) for segment in cut_segments)
        reasons: dict[str, int] = {}
        for segment in cut_segments:
            reason = str(segment.get("reason") or "other")
            reasons[reason] = reasons.get(reason, 0) + 1
        detail = "；".join(f"{reason} {count} 段" for reason, count in sorted(reasons.items())) or "无删减建议"
        decisions.append(
            {
                "kind": "edit_plan",
                "step_name": "edit_plan",
                "title": "剪辑决策",
                "status": "done",
                "summary": f"建议移除 {len(cut_segments)} 段，共 {total_cut:.1f} 秒",
                "detail": detail,
                "updated_at": _iso_or_none(editorial.created_at),
            }
        )

    if render_output is not None:
        decisions.append(
            {
                "kind": "render",
                "step_name": "render",
                "title": "渲染状态",
                "status": render_output.status,
                "summary": f"成片输出进度 {round(float(render_output.progress or 0.0) * 100)}%",
                "detail": render_output.output_path or "正在生成输出文件",
                "updated_at": _iso_or_none(render_output.created_at),
            }
        )

    dialogue_polish = next(
        (
            artifact
            for artifact in artifacts
            if artifact.artifact_type in {"dialogue_polish_plan", "ai_director_plan"}
        ),
        None,
    )
    if dialogue_polish and dialogue_polish.data_json:
        plan = dialogue_polish.data_json
        decisions.append(
            {
                "kind": "dialogue_polish",
                "step_name": "dialogue_polish",
                "title": "智能台词润色",
                "status": "done",
                "summary": f"生成 {len(plan.get('voiceover_segments') or [])} 段台词润色/重配音建议",
                "detail": str(plan.get("opening_hook") or plan.get("bridge_line") or "已输出台词润色稿"),
                "updated_at": _iso_or_none(dialogue_polish.created_at),
            }
        )

    avatar_plan = next((artifact for artifact in artifacts if artifact.artifact_type == "avatar_commentary_plan"), None)
    if avatar_plan and avatar_plan.data_json:
        plan = avatar_plan.data_json
        avatar_result = render_outputs.get("avatar_result") if isinstance(render_outputs, dict) else None
        avatar_status = _resolve_avatar_activity_status(plan, avatar_result)
        decisions.append(
            {
                "kind": "avatar_commentary",
                "step_name": "avatar_commentary",
                "title": "数字人解说",
                "status": avatar_status["status"],
                "summary": avatar_status["summary"],
                "detail": avatar_status["detail"],
                "updated_at": avatar_status["updated_at"] or _iso_or_none(avatar_plan.created_at),
            }
        )

    packaging = next((artifact for artifact in artifacts if artifact.artifact_type == "platform_packaging_md"), None)
    if packaging:
        data = packaging.data_json or {}
        title = _resolve_platform_packaging_summary_title(data)
        decisions.append(
            {
                "kind": "platform_package",
                "step_name": "platform_package",
                "title": "平台文案",
                "status": "done",
                "summary": "已生成发布文案包",
                "detail": title or packaging.storage_path,
                "updated_at": _iso_or_none(packaging.created_at),
            }
        )

    quality = next((artifact for artifact in artifacts if artifact.artifact_type == QUALITY_ARTIFACT_TYPE and artifact.data_json), None)
    if quality and quality.data_json:
        data = quality.data_json
        score = data.get("score")
        grade = str(data.get("grade") or "").strip()
        recommended_steps = [str(item).strip() for item in (data.get("recommended_rerun_steps") or []) if str(item).strip()]
        issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()]
        manual_review_required = bool(data.get("manual_review_required"))
        bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
        timing_summary = _resolve_variant_timing_summary(bundle)
        validation_summary = _summarize_variant_timeline_validation(bundle)
        validation_detail = _describe_variant_timeline_validation(bundle)
        summary_parts = []
        if grade or score is not None:
            summary_parts.append(f"{grade} {float(score):.1f}" if grade and score is not None else str(grade or score))
        if issue_codes:
            summary_parts.append(f"{len(issue_codes)} 个扣分项")
        if manual_review_required:
            summary_parts.append("人工复核")
        if timing_summary:
            summary_parts.append(timing_summary)
        if validation_summary:
            summary_parts.append(validation_summary)
        decisions.append(
            {
                "kind": "quality_assessment",
                "step_name": "final_review",
                "title": "质量评分",
                "status": "done",
                "summary": " · ".join(part for part in summary_parts if part).strip() or "质量评分已更新",
                "detail": (
                    "；".join(
                        part for part in [
                            f"问题：{', '.join(issue_codes)}" if issue_codes else "",
                            "处理：必须人工复核" if manual_review_required else "",
                            f"建议补跑：{', '.join(recommended_steps)}" if recommended_steps and not manual_review_required else "",
                            f"时间轴校验：{validation_detail}" if validation_detail else "",
                        ]
                        if part
                    )
                    or None
                ),
                "updated_at": _iso_or_none(quality.created_at),
            }
        )

    return decisions


def _normalize_platform_packaging_entries(raw_packaging: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_packaging, dict):
        return {}
    candidate = raw_packaging.get("platforms") if isinstance(raw_packaging.get("platforms"), (dict, list)) else raw_packaging
    entries: dict[str, dict[str, Any]] = {}
    if isinstance(candidate, dict):
        for key, value in candidate.items():
            platform = normalize_publication_platform(key)
            if platform and isinstance(value, dict):
                entries[platform] = dict(value)
        return entries
    if isinstance(candidate, list):
        for item in candidate:
            if not isinstance(item, dict):
                continue
            platform = normalize_publication_platform(item.get("platform") or item.get("key") or item.get("label") or item.get("name"))
            if platform:
                entries[platform] = dict(item)
    return entries


def _resolve_platform_packaging_summary_title(raw_packaging: Any) -> str:
    entries = _normalize_platform_packaging_entries(raw_packaging)
    for platform in ("douyin", "xiaohongshu", "bilibili"):
        pack = entries.get(platform) if isinstance(entries.get(platform), dict) else {}
        titles = pack.get("titles") if isinstance(pack.get("titles"), list) else []
        for item in titles:
            title = str(item or "").strip()
            if title:
                return title
    for pack in entries.values():
        if not isinstance(pack, dict):
            continue
        titles = pack.get("titles") if isinstance(pack.get("titles"), list) else []
        for item in titles:
            title = str(item or "").strip()
            if title:
                return title
    return ""


def _build_activity_events(
    steps: list[JobStep],
    artifacts: list[Artifact],
    timelines: list[Timeline],
    render_output: RenderOutput | None,
    *,
    job: Job | None = None,
    review_actions: list[ReviewAction] | None = None,
) -> list[dict]:
    events: list[dict] = []
    terminal_step = _latest_terminal_step(steps, statuses={"failed", "cancelled"}) if steps else None

    if job is not None and job.status in {"failed", "cancelled"} and job.error_message:
        events.append(
            {
                "timestamp": _iso_or_none(job.updated_at),
                "type": "error" if job.status == "failed" else "cancelled",
                "status": job.status,
                "step_name": terminal_step.step_name if terminal_step is not None else None,
                "title": "任务失败" if job.status == "failed" else "任务已取消",
                "detail": job.error_message,
            }
        )

    for step in steps:
        label = STEP_LABELS.get(step.step_name, step.step_name)
        metadata = step.metadata_ or {}
        elapsed_seconds = _step_elapsed_seconds(step)
        if step.started_at:
            events.append(
                {
                    "timestamp": _iso_or_none(step.started_at),
                    "type": "step",
                    "status": "running" if step.status == "running" else "started",
                    "step_name": step.step_name,
                    "title": f"{label}开始",
                    "detail": None,
                }
            )
        if step.finished_at:
            if step.status in {"failed", "cancelled"}:
                detail = _coalesce_step_error_detail(step, fallback=step.error_message)
            else:
                detail = step.error_message or metadata.get("detail")
            events.append(
                {
                    "timestamp": _iso_or_none(step.finished_at),
                    "type": "step",
                    "status": step.status,
                    "step_name": step.step_name,
                    "title": f"{label}{'完成' if step.status == 'done' else '结束'}",
                    "detail": _decorate_step_detail(
                        detail,
                        elapsed_seconds,
                        running=False,
                    ),
                }
            )
        updated_at = metadata.get("updated_at")
        if step.status == "running" and updated_at:
            worker_active = _step_has_worker_started(step)
            events.append(
                {
                    "timestamp": updated_at,
                    "type": "progress",
                    "status": "running" if worker_active else "queued",
                    "step_name": step.step_name,
                    "title": label,
                    "detail": _decorate_step_detail(metadata.get("detail"), elapsed_seconds, running=worker_active),
                }
            )

    for artifact in artifacts:
        summary = _artifact_event_summary(artifact)
        if summary:
            events.append(
                {
                    "timestamp": _iso_or_none(artifact.created_at),
                    "type": "artifact",
                    "status": "done",
                    "step_name": summary.get("step_name"),
                    "title": summary["title"],
                    "detail": summary["detail"],
                }
            )

    for timeline in timelines:
        if timeline.timeline_type == "editorial":
            events.append(
                {
                    "timestamp": _iso_or_none(timeline.created_at),
                    "type": "decision",
                    "status": "done",
                    "step_name": "edit_plan",
                    "title": "剪辑时间线已生成",
                    "detail": "系统已产出保留/删除片段决策。",
                }
            )

    if render_output is not None:
        events.append(
            {
                "timestamp": _iso_or_none(render_output.created_at),
                "type": "render",
                "status": render_output.status,
                "step_name": "render",
                "title": "渲染输出",
                "detail": f"当前进度 {round(float(render_output.progress or 0.0) * 100)}%",
            }
        )

    for action in review_actions or []:
        summary = _review_action_event_summary(action, steps)
        if summary:
            events.append(
                {
                    "timestamp": _iso_or_none(action.created_at),
                    "type": "review_action",
                    "status": summary["status"],
                    "step_name": summary.get("step_name"),
                    "title": summary["title"],
                    "detail": summary.get("detail"),
                }
            )

    events = [event for event in events if event["timestamp"]]
    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events[:20]


def _review_action_event_summary(action: ReviewAction, steps: list[JobStep]) -> dict[str, str] | None:
    if str(action.target_type or "").strip() != "quality_rerun":
        return None

    rerun_step_name = str(action.action or "").strip()
    rerun_step = next((step for step in steps if step.step_name == rerun_step_name), None)
    metadata = dict((rerun_step.metadata_ or {}) if rerun_step is not None else {})
    via = str(metadata.get("rerun_requested_via") or "").strip()
    issue_codes = [str(item).strip() for item in (metadata.get("rerun_issue_codes") or []) if str(item).strip()]
    note = str(metadata.get("rerun_request_note") or "").strip()
    rerun_steps = [str(item).strip() for item in (metadata.get("rerun_steps") or []) if str(item).strip()]

    via_label = {
        "web": "Web",
        "telegram": "Telegram",
    }.get(via, via or "系统")
    chain_text = " -> ".join(rerun_steps) if rerun_steps else rerun_step_name
    detail_parts = [
        f"触发来源：{via_label}",
        f"问题：{', '.join(issue_codes)}" if issue_codes else "",
        f"回退链路：{chain_text}" if chain_text else "",
        f"备注：{note}" if note else "",
    ]
    return {
        "step_name": rerun_step_name or None,
        "title": f"已请求从 {rerun_step_name} 重跑" if rerun_step_name else "已请求重跑",
        "detail": "；".join(part for part in detail_parts if part) or None,
        "status": "processing",
    }


def _artifact_event_summary(artifact: Artifact) -> dict | None:
    data = artifact.data_json or {}
    if artifact.artifact_type == "media_meta":
        width = data.get("width")
        height = data.get("height")
        duration = data.get("duration")
        return {
            "step_name": "probe",
            "title": "媒体参数已识别",
            "detail": f"{width}×{height} · {duration:.1f}s" if width and height and duration else "媒体信息已写入",
        }
    if artifact.artifact_type == "content_profile_draft":
        return {
            "step_name": "content_profile",
            "title": "内容摘要草稿已生成",
            "detail": str(data.get("summary") or data.get("video_theme") or "等待人工确认"),
        }
    if artifact.artifact_type in {"content_profile", "content_profile_final"}:
        return {
            "step_name": "summary_review" if artifact.artifact_type == "content_profile_final" else "content_profile",
            "title": "内容摘要已确认",
            "detail": str(data.get("summary") or data.get("video_theme") or "内容识别完成"),
        }
    if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT:
        score_raw = data.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        blocking = bool(data.get("blocking"))
        reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
        warnings = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
        detail = (
            (f"未通过：{reasons[0]}" if reasons else "字幕阶段质检未通过")
            if blocking
            else (warnings[0] if warnings else "字幕阶段质检通过")
        )
        prefix = f"{score:.1f}分" if score is not None else "字幕质检"
        return {
            "step_name": "subtitle_postprocess",
            "title": "字幕阶段验收已生成",
            "detail": f"{prefix} · {detail}",
        }
    if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH:
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        patch_count = int(metrics.get("patch_count") or 0)
        pending = int(metrics.get("pending_count") or 0)
        auto_applied = int(metrics.get("auto_applied_count") or 0)
        return {
            "step_name": "subtitle_term_resolution",
            "title": "字幕术语解析已生成",
            "detail": f"patch {patch_count} 条 · 待确认 {pending} 条 · 自动接受 {auto_applied} 条",
        }
    if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT:
        score_raw = data.get("score")
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        blocking = bool(data.get("blocking"))
        reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
        warnings = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
        detail = (
            (f"未通过：{reasons[0]}" if reasons else "字幕一致性未通过")
            if blocking
            else (warnings[0] if warnings else "字幕一致性通过")
        )
        prefix = f"{score:.1f}分" if score is not None else "一致性审校"
        return {
            "step_name": "subtitle_consistency_review",
            "title": "字幕一致性审校已生成",
            "detail": f"{prefix} · {detail}",
        }
    if artifact.artifact_type == "platform_packaging_md":
        detail = _resolve_platform_packaging_summary_title(data) or artifact.storage_path or "发布文案已写入 Markdown"
        return {
            "step_name": "platform_package",
            "title": "平台文案已生成",
            "detail": detail,
        }
    if artifact.artifact_type in {"dialogue_polish_plan", "ai_director_plan"}:
        return {
            "step_name": "dialogue_polish",
            "title": "智能台词润色已生成",
            "detail": str(data.get("opening_hook") or "已输出台词润色与重配音计划"),
        }
    if artifact.artifact_type == "avatar_commentary_plan":
        placement = str(data.get("overlay_position") or data.get("layout_template") or "").strip()
        return {
            "step_name": "avatar_commentary",
            "title": "数字人解说计划已生成",
            "detail": (
                f"{len(data.get('segments') or [])} 段解说位待渲染"
                + (f" · {placement}" if placement else "")
            ),
        }
    if artifact.artifact_type == "render_outputs":
        avatar_result = data.get("avatar_result") if isinstance(data, dict) else None
        if isinstance(avatar_result, dict) and avatar_result.get("status"):
            return {
                "step_name": "avatar_commentary",
                "title": "数字人成片结果已回写",
                "detail": str(avatar_result.get("detail") or avatar_result.get("status") or "数字人结果已更新"),
            }
    if artifact.artifact_type == STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE:
        return _stuck_step_diagnostic_summary(data)
    if artifact.artifact_type == QUALITY_ARTIFACT_TYPE:
        score = data.get("score") if isinstance(data, dict) else None
        grade = str(data.get("grade") or "").strip() if isinstance(data, dict) else ""
        issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()] if isinstance(data, dict) else []
        title = "质量评分已更新"
        detail = " · ".join(
            part
            for part in [
                f"{grade} {float(score):.1f}" if grade and score is not None else (str(score) if score is not None else ""),
                f"{len(issue_codes)} 个扣分项" if issue_codes else "",
            ]
            if part
        )
        return {
            "step_name": "final_review",
            "title": title,
            "detail": detail or "质量评分已写入",
        }
    return None


def _latest_terminal_step(
    steps: list[JobStep],
    *,
    statuses: set[str] | None = None,
) -> JobStep | None:
    if not steps:
        return None
    allowed_statuses = set(statuses or {"done", "failed", "skipped", "cancelled"})
    for step in reversed(_ordered_steps(steps)):
        if step.status in allowed_statuses:
            return step
    return None


def _coalesce_step_error_detail(step: JobStep, *, fallback: str | None = None) -> str | None:
    metadata = step.metadata_ or {}
    details = []

    step_error = str(step.error_message or "").strip()
    if step_error:
        details.append(step_error)

    detail = str(metadata.get("detail") or "").strip()
    if detail:
        details.append(detail)

    recovery_summary = str(metadata.get("recovery_summary") or "").strip()
    if recovery_summary:
        details.append(f"恢复建议：{recovery_summary}")

    recovery_root_cause = str(metadata.get("recovery_root_cause") or "").strip()
    if recovery_root_cause:
        details.append(f"恢复根因：{recovery_root_cause}")

    if fallback:
        fallback_text = str(fallback).strip()
        if fallback_text and fallback_text not in details:
            details.append(fallback_text)

    cleaned_details = [item for item in details if item]
    return " · ".join(cleaned_details) if cleaned_details else None


def _pending_step_transition_detail(
    detail: Any,
    step: JobStep,
    steps: list[JobStep],
) -> str:
    raw_detail = str(detail or "").strip()
    if raw_detail:
        return raw_detail
    if _are_previous_steps_complete(steps, step.step_name):
        standardized_detail = _pending_step_standard_detail(step.step_name)
        if standardized_detail:
            return standardized_detail
        return "等待调度器派发。"
    return "等待前序步骤完成。"


def _stuck_step_diagnostic_summary(data: object) -> dict[str, str] | None:
    payload = data if isinstance(data, dict) else {}
    step_name = str(payload.get("step_name") or "未命名步骤").strip()
    summary = str(payload.get("summary") or "").strip()
    root_cause = str(payload.get("root_cause") or "").strip()
    confidence = payload.get("confidence")
    evidence = payload.get("evidence") if isinstance(payload, dict) else None
    recommended_action = payload.get("recommended_action") if isinstance(payload, dict) else None
    action_parts: list[str] = []
    if isinstance(recommended_action, dict):
        action_kind = str(recommended_action.get("kind") or "").strip()
        action_reason = str(recommended_action.get("reason") or "").strip()
        if action_kind:
            action_parts.append(action_kind)
        if action_reason:
            action_parts.append(action_reason)
    action = " / ".join(part for part in action_parts if part)

    stale_after = ""
    if isinstance(evidence, dict):
        stale_after_sec = evidence.get("stale_after_sec")
        if stale_after_sec is not None:
            stale_after = f"（阈值 {stale_after_sec}s）"

    details: list[str] = []
    if summary:
        details.append(summary)
    if root_cause:
        details.append(f"根因：{root_cause}")
    if action:
        details.append(f"恢复建议：{action}{stale_after}")
    if isinstance(confidence, (float, int)):
        details.append(f"置信度：{float(confidence):.2f}")

    return {
        "step_name": step_name or None,
        "title": f"{step_name} 卡住诊断",
        "detail": " · ".join(part for part in details if part) or "检测到步骤卡住并已写入诊断记录。",
    }


def _resolve_avatar_activity_status(
    plan: dict,
    avatar_result: dict | None,
) -> dict[str, str | None]:
    placement = str(plan.get("overlay_position") or plan.get("layout_template") or plan.get("provider") or "").strip()
    if avatar_result:
        status_value = str(avatar_result.get("status") or "").strip().lower()
        if status_value == "done":
            summary = "数字人口播已合成进成片"
            detail = str(
                avatar_result.get("detail")
                or avatar_result.get("profile_name")
                or placement
                or "数字人画中画已完成"
            )
            return {"status": "done", "summary": summary, "detail": detail, "updated_at": None}
        if status_value in {"degraded", "failed"}:
            summary = "数字人未写入成片，已回退普通成片"
            detail = str(
                avatar_result.get("detail")
                or avatar_result.get("reason")
                or plan.get("provider")
                or "数字人渲染失败，已自动降级"
            )
            return {"status": "failed", "summary": summary, "detail": detail, "updated_at": None}

    render_execution = plan.get("render_execution") if isinstance(plan, dict) else None
    render_status = str((render_execution or {}).get("status") or "").strip().lower()
    if render_status in {"success", "partial"}:
        return {
            "status": "done",
            "summary": "数字人素材已生成，等待合成进成片",
            "detail": str(placement or "数字人素材已准备完成"),
            "updated_at": None,
        }
    if render_status in {"failed"}:
        return {
            "status": "failed",
            "summary": "数字人素材生成失败",
            "detail": str((render_execution or {}).get("error") or plan.get("provider") or "数字人生成失败"),
            "updated_at": None,
        }

    return {
        "status": "done",
        "summary": f"规划 {len(plan.get('segments') or [])} 段数字人口播插入位",
        "detail": str(placement or "已生成数字人解说计划"),
        "updated_at": None,
    }


def _step_elapsed_seconds(step: JobStep) -> float | None:
    metadata = step.metadata_ or {}
    raw_elapsed = metadata.get("elapsed_seconds")
    if raw_elapsed is not None:
        try:
            return max(0.0, float(raw_elapsed))
        except (TypeError, ValueError):
            pass
    if step.started_at is None:
        return None
    start_time = _coerce_utc(step.started_at)
    end_time = _coerce_utc(step.finished_at) if step.finished_at is not None else datetime.now(timezone.utc)
    return max(0.0, (end_time - start_time).total_seconds())


def _decorate_step_detail(detail: str | None, elapsed_seconds: float | None, *, running: bool) -> str | None:
    elapsed_text = _format_elapsed(elapsed_seconds)
    base = (detail or "").strip()
    if elapsed_text:
        suffix = f"已运行 {elapsed_text}" if running else f"用时 {elapsed_text}"
        if base:
            if suffix in base or "用时 " in base or "已运行 " in base:
                return base
            return f"{base} · {suffix}"
        return suffix
    return base or None


def _format_elapsed(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 10:
        return f"{seconds:.1f}s"
    total_seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minute}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _step_has_worker_started(step: JobStep) -> bool:
    metadata = step.metadata_ or {}
    worker_started_at = metadata.get("worker_started_at")
    if not isinstance(worker_started_at, str) or not worker_started_at.strip():
        return False
    try:
        worker_started = _coerce_utc(datetime.fromisoformat(worker_started_at))
    except ValueError:
        return False

    dispatched_at = metadata.get("dispatched_at")
    if isinstance(dispatched_at, str) and dispatched_at.strip():
        try:
            dispatched = _coerce_utc(datetime.fromisoformat(dispatched_at))
        except ValueError:
            dispatched = None
        if dispatched is not None and worker_started < dispatched:
            return False
    return True


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _attach_job_previews(jobs: list[Job], *, lightweight: bool = False) -> None:
    for job in jobs:
        _attach_job_preview(job, lightweight=lightweight)


def _attach_job_preview(job: Job, *, lightweight: bool = False) -> None:
    if job.steps:
        job.steps.sort(key=_step_sort_key)
    source_context = _extract_job_source_context_from_steps(job.steps or [])
    job.merged_source_names = _resolve_job_merged_source_names(job)
    job.video_description = str(source_context.get("video_description") or "").strip() or None
    preview = _resolve_job_content_preview(job.artifacts or [], apply_review_memory=not lightweight)
    job.content_subject = preview["subject"]
    job.content_summary = preview["summary"]
    quality_preview = _resolve_job_quality_preview(job.artifacts or [])
    job.quality_score = quality_preview["score"]
    job.quality_grade = quality_preview["grade"]
    job.quality_summary = quality_preview["summary"]
    job.quality_issue_codes = quality_preview["issue_codes"]
    job.timeline_diagnostics = _resolve_job_timeline_diagnostics_preview(job.artifacts or [])
    avatar_preview = _resolve_job_avatar_preview(job)
    job.avatar_delivery_status = avatar_preview["status"]
    job.avatar_delivery_summary = avatar_preview["summary"]
    auto_review_preview = _resolve_job_auto_review_preview(job)
    job.auto_review_mode_enabled = bool(auto_review_preview["mode_enabled"])
    job.auto_review_status = auto_review_preview["status"]
    job.auto_review_summary = auto_review_preview["summary"]
    job.auto_review_reasons = list(auto_review_preview["reasons"] or [])
    review_preview = _resolve_job_review_context(job)
    job.review_step = review_preview["step_name"]
    job.review_label = review_preview["label"]
    job.review_detail = review_preview["detail"]
    job.awaiting_initialization = str(job.status or "").strip() == "awaiting_init"
    job.awaiting_manual_edit = str(job.status or "").strip() == "awaiting_manual_edit"
    if job.awaiting_manual_edit:
        manual_preview = _resolve_manual_editor_waiting_context(job)
        job.review_label = manual_preview["label"]
        job.review_detail = manual_preview["detail"]
    publication_preview = _resolve_job_publication_preview(job)
    job.publication_status = publication_preview["status"]
    job.publication_summary = publication_preview["summary"]
    job.queue_task_kind = _resolve_job_queue_task_kind(job)
    job.queue_thumbnail_source = "cover" if _resolve_job_queue_cover_path(job) else "content_profile"
    job.queue_thumbnail_version = _resolve_job_queue_thumbnail_version(job)
    _reconcile_job_preview_terminal_status(job)
    job.progress_percent = _calculate_job_progress_percent(job)


def _collapse_jobs_for_primary_queue(jobs: list[Job]) -> list[Job]:
    collapsed: list[Job] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for job in jobs:
        family_key = _job_queue_family_key(job)
        if family_key in seen_keys:
            continue
        seen_keys.add(family_key)
        collapsed.append(job)
    return collapsed


def _job_queue_family_key(job: Job) -> tuple[str, str, str, str]:
    identity = (
        str(getattr(job, "file_hash", "") or "").strip().lower()
        or str(getattr(job, "source_path", "") or "").strip().lower()
        or str(getattr(job, "source_name", "") or "").strip().lower()
    )
    workflow_template = str(getattr(job, "workflow_template", "") or "").strip().lower()
    output_dir = str(getattr(job, "output_dir", "") or "").strip().lower()
    task_kind = str(getattr(job, "queue_task_kind", "") or "").strip().lower()
    return (identity, workflow_template, output_dir, task_kind)


def _reconcile_job_preview_terminal_status(job: Job) -> None:
    normalized_status = str(getattr(job, "status", "") or "").strip().lower()
    if normalized_status == "done":
        return
    render_step = _find_step(list(getattr(job, "steps", None) or []), "render")
    if render_step is None or str(render_step.status or "").strip().lower() != "done":
        return
    artifacts = list(getattr(job, "artifacts", None) or [])
    render_outputs_artifact = next(
        (
            artifact
            for artifact in artifacts
            if str(getattr(artifact, "artifact_type", "") or "").strip() == "render_outputs"
            and isinstance(getattr(artifact, "data_json", None), dict)
        ),
        None,
    )
    render_outputs = dict(getattr(render_outputs_artifact, "data_json", None) or {})
    packaged_mp4 = str(
        render_outputs.get("packaged_mp4")
        or render_outputs.get("output_path")
        or ((render_outputs.get("local") or {}).get("packaged_mp4") if isinstance(render_outputs.get("local"), dict) else "")
        or ""
    ).strip()
    if not packaged_mp4:
        return
    job.status = "done"
    job.error_message = None


def _resolve_job_queue_task_kind(job: Job) -> str:
    if _job_is_remix_production(job):
        return "remix_production"
    if str(getattr(job, "workflow_mode", "") or "").strip() == "smart_director":
        return "smart_director"
    if str(getattr(job, "workflow_template", "") or "").strip() == "intelligent_publish":
        return "publication"
    if str(getattr(job, "status", "") or "").strip() == "published":
        return "publication"
    steps = [step for step in list(getattr(job, "steps", None) or []) if str(getattr(step, "step_name", "") or "").strip()]
    if steps:
        return "edit"
    try:
        attempts_unloaded = "publication_attempts" in inspect(job).unloaded
    except Exception:
        attempts_unloaded = True
    if not attempts_unloaded and list(getattr(job, "publication_attempts", None) or []):
        return "publication"
    return "edit"


def _resolve_job_queue_cover_path(job: Job) -> Path | None:
    for artifact in list(getattr(job, "artifacts", None) or []):
        if str(getattr(artifact, "artifact_type", "") or "") != "render_outputs":
            continue
        data = getattr(artifact, "data_json", None)
        if not isinstance(data, dict):
            continue
        path = _normalize_existing_image_path(data.get("cover"))
        if path is not None:
            return path
        for value in list(data.get("cover_variants") or []):
            path = _normalize_existing_image_path(value)
            if path is not None:
                return path

    source_context = _extract_job_source_context_from_steps(list(getattr(job, "steps", None) or []))
    remix_payload = source_context.get("remix_production") if isinstance(source_context, dict) else None
    if isinstance(remix_payload, dict):
        raw_output_dir = str(getattr(job, "output_dir", "") or "").strip()
        if raw_output_dir:
            cover_path = _resolve_remix_production_output_cover_path(
                Path(raw_output_dir).expanduser(),
                episode=int(remix_payload.get("episode") or 0),
            )
            if cover_path is not None:
                return cover_path

    try:
        if "publication_attempts" in inspect(job).unloaded:
            return None
    except Exception:
        return None
    for attempt in sorted(
        list(getattr(job, "publication_attempts", None) or []),
        key=lambda item: getattr(item, "updated_at", None) or getattr(item, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    ):
        for value in _iter_publication_cover_path_candidates(attempt):
            path = _normalize_existing_image_path(value)
            if path is not None:
                return path
    return None


def _resolve_job_queue_thumbnail_version(job: Job) -> str:
    updated_at = str(getattr(job, "updated_at", "") or "").strip()
    source = str(getattr(job, "queue_thumbnail_source", "") or "").strip()
    if source == "content_profile":
        return f"{updated_at}:{_CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION}"
    return updated_at


def _iter_publication_cover_path_candidates(attempt: Any) -> list[str]:
    candidates: list[str] = []

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)

    request_payload = getattr(attempt, "request_payload", None)
    if isinstance(request_payload, dict):
        add(request_payload.get("cover_path"))
        for slot in request_payload.get("cover_slots") or []:
            if isinstance(slot, dict):
                add(slot.get("cover_path"))
        copy_material = request_payload.get("copy_material")
        if isinstance(copy_material, dict):
            add(copy_material.get("cover_path"))
            for slot in copy_material.get("cover_slots") or []:
                if isinstance(slot, dict):
                    add(slot.get("cover_path"))

    response_payload = getattr(attempt, "response_payload", None)
    if isinstance(response_payload, dict):
        material_integrity = response_payload.get("material_integrity")
        if isinstance(material_integrity, dict):
            fields = material_integrity.get("fields")
            cover = fields.get("cover") if isinstance(fields, dict) else None
            if isinstance(cover, dict):
                add(cover.get("expected_path"))
        error = response_payload.get("error")
        details = error.get("details") if isinstance(error, dict) else None
        fields = details.get("fields") if isinstance(details, dict) else None
        cover = fields.get("cover") if isinstance(fields, dict) else None
        if isinstance(cover, dict):
            add(cover.get("expected_path"))
        for action in _extract_publication_actions(response_payload):
            if str(action.get("kind") or "").strip() == "cover_verified":
                add(action.get("path"))
    return candidates


def _extract_publication_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            maybe_final_publish = value.get("final_publish")
            if isinstance(maybe_final_publish, dict):
                raw_actions = maybe_final_publish.get("actions")
                if isinstance(raw_actions, list):
                    actions.extend(item for item in raw_actions if isinstance(item, dict))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return actions


def _normalize_existing_image_path(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    cached_path = _publication_cover_cache_path(text, suffix=path.suffix.lower())
    if cached_path.exists() and cached_path.is_file():
        return cached_path
    try:
        if path.exists() and path.is_file():
            return path
    except OSError:
        return None
    return None


def _publication_cover_cache_path(source_path: str, *, suffix: str) -> Path:
    safe_suffix = suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
    cache_root = Path(get_settings().job_storage_dir).expanduser().parent / "publication-cover-cache"
    digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()
    return cache_root / f"{digest}{safe_suffix}"


def _resolve_job_publication_preview(job: Job) -> dict[str, str | None]:
    if str(job.status or "").strip() not in {"done", "published"}:
        return {"status": "not_applicable", "summary": None}
    try:
        if "publication_attempts" in inspect(job).unloaded:
            return {"status": "unpublished", "summary": None}
    except Exception:
        return {"status": "unpublished", "summary": None}
    attempts = list(job.publication_attempts or [])
    active_attempts = [
        attempt
        for attempt in attempts
        if str(getattr(attempt, "status", "") or "").strip() not in {"failed", "cancelled"}
    ]
    if not active_attempts:
        return {"status": "unpublished", "summary": None}
    labels = []
    for attempt in active_attempts:
        label = str(getattr(attempt, "platform_label", "") or getattr(attempt, "platform", "") or "").strip()
        if label and label not in labels:
            labels.append(label)
    summary = f"已提交发布：{' / '.join(labels[:4])}" if labels else "已提交发布"
    if len(labels) > 4:
        summary += f" +{len(labels) - 4}"
    return {"status": "published", "summary": summary}


def _extract_job_source_context_from_steps(steps: list[JobStep]) -> dict[str, Any]:
    return extract_content_profile_source_context_from_steps(steps)


def _resolve_job_merged_source_names(job: Job) -> list[str]:
    return resolve_job_merged_source_names(job)


def _calculate_job_progress_percent(job: Job) -> int:
    normalized_status = str(job.status or "").strip()
    if normalized_status in {"done", "published"}:
        return 100

    steps = list(job.steps or [])
    if not steps:
        return 0

    if _job_is_remix_production(job):
        remix_step = _find_step(steps, REMIX_PRODUCTION_STEP_NAME)
        if remix_step is not None and remix_step.status == "done":
            return 100
        if normalized_status in {"failed", "cancelled"}:
            return 0
        if remix_step is not None and remix_step.status == "running":
            metadata = remix_step.metadata_ or {}
            try:
                return max(1, min(95, round(float(metadata.get("progress") or 0.5) * 100)))
            except (TypeError, ValueError):
                return 50
        return 0

    if normalized_status == "awaiting_manual_edit":
        render_index = STEP_ORDER.get("render", len(PIPELINE_STEPS))
        completed_before_render = sum(
            1
            for step in steps
            if STEP_ORDER.get(step.step_name, len(PIPELINE_STEPS)) < render_index
            and step.status in {"done", "skipped"}
        )
        return min(95, round((completed_before_render / max(1, len(PIPELINE_STEPS))) * 100))

    total = len(steps)
    done_count = sum(1 for step in steps if step.status in {"done", "skipped"})
    running_count = sum(1 for step in steps if step.status == "running" and _step_has_worker_started(step))
    base_progress = done_count / total
    running_bonus = (0.5 / total) if running_count else 0.0
    progress = max(0.0, min(1.0, base_progress + running_bonus))

    if normalized_status in {"failed", "cancelled"}:
        return round(base_progress * 100)
    return round(progress * 100)


def _ordered_steps(steps: list[JobStep]) -> list[JobStep]:
    return sorted(steps, key=_step_sort_key)


def _step_sort_key(step: JobStep) -> tuple[int, datetime]:
    created = step.started_at or step.finished_at or datetime.min.replace(tzinfo=timezone.utc)
    return (STEP_ORDER.get(step.step_name, len(STEP_ORDER)), created)


def _find_step(steps: list[JobStep], step_name: str) -> JobStep | None:
    return next((step for step in steps if step.step_name == step_name), None)


def _are_previous_steps_complete(steps: list[JobStep], step_name: str) -> bool:
    step_index = STEP_ORDER.get(step_name, len(STEP_ORDER))
    for step in _ordered_steps(steps):
        if STEP_ORDER.get(step.step_name, len(STEP_ORDER)) >= step_index:
            break
        if step.status not in {"done", "skipped"}:
            return False
    return True


def _has_reached_step(job: Job, step_name: str) -> bool:
    steps = list(job.steps or [])
    target = _find_step(steps, step_name)
    if target is None:
        return False
    if target.status in {"running", "done", "failed", "skipped"}:
        return True
    if target.attempt > 0 or target.started_at is not None or target.finished_at is not None:
        return True
    return any(
        STEP_ORDER.get(step.step_name, -1) > STEP_ORDER.get(step_name, -1)
        and step.status in {"running", "done", "failed", "skipped"}
        for step in steps
    )


def _resolve_job_content_preview(
    artifacts: list[Artifact],
    *,
    apply_review_memory: bool = True,
) -> dict[str, str | None]:
    profile = _select_preview_artifact(artifacts)
    if not profile or not profile.data_json:
        return {"subject": None, "summary": None}

    data = profile.data_json
    def _normalize_preview_value(value: object) -> str:
        normalized = str(value or "").strip()
        if normalized.lower() in {"unknown", "n/a", "none", "null"}:
            return ""
        if normalized in {"未知", "待确认", "内容待确认", "待人工确认", "未识别"}:
            return ""
        return normalized

    product = " ".join(
        part.strip()
        for part in [
            _normalize_preview_value(data.get("subject_brand")),
            _normalize_preview_value(data.get("subject_model")),
        ]
        if part and str(part).strip()
    ).strip()
    subject_parts = [
        product,
        _normalize_preview_value(data.get("subject_type")),
        _normalize_preview_value(data.get("video_theme")),
    ]
    subject = " · ".join(part for part in subject_parts if part).strip() or None
    summary = str(data.get("summary") or data.get("hook_line") or "").strip() or None
    if apply_review_memory:
        subject = _normalize_preview_text_with_review_memory(subject, data)
        summary = _normalize_preview_text_with_review_memory(summary, data)
    return {"subject": subject, "summary": summary}


def _normalize_preview_text_with_review_memory(text: str | None, data: dict[str, Any]) -> str | None:
    value = str(text or "").strip() or None
    if not value:
        return None
    if not _preview_has_trusted_review_context(data):
        return value
    review_memory = _build_preview_review_memory(data)
    if not review_memory:
        return value
    normalized = _apply_preview_alias_corrections(value, review_memory)
    return str(normalized or "").strip() or value


def _preview_has_trusted_review_context(data: dict[str, Any]) -> bool:
    payload = data if isinstance(data, dict) else {}
    content_understanding = payload.get("content_understanding") if isinstance(payload.get("content_understanding"), dict) else {}
    video_type = normalize_video_type(
        str(content_understanding.get("video_type") or payload.get("content_kind") or "").strip()
    )
    if not video_type:
        return False
    explicit_domain = str(content_understanding.get("content_domain") or payload.get("subject_domain") or "").strip()
    if explicit_domain:
        return True
    context_profile = {
        "subject_type": str(payload.get("subject_type") or "").strip(),
        "video_theme": str(payload.get("video_theme") or "").strip(),
    }
    detected_domains = detect_glossary_domains(
        workflow_template=str(payload.get("workflow_template") or "").strip() or None,
        content_profile=context_profile,
        subtitle_items=None,
    )
    return bool(detected_domains)


def _build_preview_review_memory(data: dict[str, Any]) -> dict[str, Any] | None:
    payload = data if isinstance(data, dict) else {}
    content_understanding = payload.get("content_understanding") if isinstance(payload.get("content_understanding"), dict) else {}
    subject_domain = str(content_understanding.get("content_domain") or payload.get("subject_domain") or "").strip() or None
    preview_profile = {
        "workflow_template": str(payload.get("workflow_template") or "").strip(),
        "content_kind": str(payload.get("content_kind") or "").strip(),
        "subject_domain": subject_domain or "",
        "subject_brand": str(payload.get("subject_brand") or "").strip(),
        "subject_model": str(payload.get("subject_model") or "").strip(),
        "subject_type": str(payload.get("subject_type") or "").strip(),
        "video_theme": str(payload.get("video_theme") or "").strip(),
    }
    return build_subtitle_review_memory(
        workflow_template=preview_profile["workflow_template"] or None,
        subject_domain=subject_domain,
        source_name=str(payload.get("source_name") or "").strip() or None,
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile=preview_profile,
        include_recent_terms=False,
        include_recent_examples=False,
    )


def _apply_preview_alias_corrections(text: str, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    for item in (review_memory or {}).get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct or wrong == correct:
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)
    return result


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_job_avatar_preview(job: Job) -> dict[str, str | None]:
    enabled_modes = set(getattr(job, "enhancement_modes", []) or [])
    if "avatar_commentary" not in enabled_modes:
        return {"status": None, "summary": None}

    artifacts = list(job.artifacts or [])
    render_outputs_artifact = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "render_outputs" and artifact.data_json),
        None,
    )
    render_outputs = render_outputs_artifact.data_json if render_outputs_artifact else {}
    avatar_result = render_outputs.get("avatar_result") if isinstance(render_outputs, dict) else None
    if isinstance(avatar_result, dict):
        status = str(avatar_result.get("status") or "").strip().lower()
        if status == "done":
            return {
                "status": "done",
                "summary": str(avatar_result.get("detail") or "数字人口播已写入成片"),
            }
        if status in {"degraded", "failed"}:
            return {
                "status": "failed",
                "summary": str(avatar_result.get("detail") or "数字人未写入成片，已回退普通成片"),
            }

    avatar_plan = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "avatar_commentary_plan" and artifact.data_json),
        None,
    )
    if avatar_plan is None:
        if not _has_reached_step(job, "avatar_commentary"):
            return {"status": None, "summary": None}
        avatar_step = _find_step(job.steps or [], "avatar_commentary")
        if avatar_step and avatar_step.status == "running":
            return {
                "status": "running",
                "summary": str((avatar_step.metadata_ or {}).get("detail") or "正在生成数字人计划"),
            }
        if job.status in {"failed", "cancelled"} or (avatar_step and avatar_step.status == "failed"):
            return {"status": "failed", "summary": "数字人流程未完成"}
        return {"status": "pending", "summary": "等待生成数字人计划"}

    plan = avatar_plan.data_json or {}
    render_execution = plan.get("render_execution") if isinstance(plan, dict) else None
    render_status = str((render_execution or {}).get("status") or "").strip().lower()
    if render_status in {"success", "partial"}:
        return {"status": "running", "summary": "数字人素材已生成，等待合成进成片"}
    if render_status == "failed":
        return {
            "status": "failed",
            "summary": str((render_execution or {}).get("error") or "数字人素材生成失败"),
        }
    return {"status": "running", "summary": "数字人计划已生成，等待渲染落地"}


def _resolve_job_auto_review_preview(job: Job) -> dict[str, Any]:
    review_step = _find_step(list(job.steps or []), "summary_review")
    profile_artifact = _select_preview_artifact(list(job.artifacts or []))
    profile_payload = profile_artifact.data_json if profile_artifact and isinstance(profile_artifact.data_json, dict) else {}
    automation = profile_payload.get("automation_review") if isinstance(profile_payload.get("automation_review"), dict) else {}

    auto_confirmed = bool((review_step.metadata_ or {}).get("auto_confirmed")) if review_step is not None else False
    if not auto_confirmed:
        auto_confirmed = str(profile_payload.get("review_mode") or "").strip().lower() == "auto_confirmed"
    if auto_confirmed:
        detail = str((review_step.metadata_ or {}).get("detail") or "").strip() if review_step is not None else ""
        return {
            "mode_enabled": True,
            "status": "applied",
            "summary": detail or "异常门未发现阻塞问题，已自动继续执行。",
            "reasons": [],
        }

    if not profile_payload:
        waiting_detail = "异常门已启用，等待内容画像后自动判断。"
        if _has_reached_step(job, "content_profile"):
            waiting_detail = "异常门已启用，等待系统完成自动判断。"
        return {
            "mode_enabled": True,
            "status": "enabled",
            "summary": waiting_detail,
            "reasons": [],
        }

    blocking_reasons = [
        str(item).strip()
        for item in (automation.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    review_reasons = [
        str(item).strip()
        for item in (automation.get("review_reasons") or [])
        if str(item).strip()
    ]
    quality_gate_passed = bool(automation.get("quality_gate_passed"))
    score = _coerce_float(automation.get("score"))
    threshold = _coerce_float(automation.get("threshold"))

    reasons: list[str] = []
    if blocking_reasons:
        reasons.extend(blocking_reasons)
    elif review_reasons:
        reasons.extend(review_reasons)

    if blocking_reasons:
        summary = "异常门已暂停，本次命中需要人工处理的阻塞问题。"
        status = "blocked"
    elif not quality_gate_passed:
        if score is not None and threshold is not None:
            summary = f"异常门未阻塞，当前摘要得分 {score:.2f} 低于参考阈值 {threshold:.2f}，将由后续质量门自动处理。"
        else:
            summary = "异常门未阻塞，当前摘要低于参考阈值，将由后续质量门自动处理。"
        status = "enabled"
    else:
        summary = "异常门已启用，未发现阻塞问题时会自动继续。"
        status = "enabled"

    return {
        "mode_enabled": True,
        "status": status,
        "summary": summary,
        "reasons": reasons,
    }


def _resolve_job_quality_preview(artifacts: list[Artifact]) -> dict[str, Any]:
    quality = next(
        (artifact for artifact in artifacts if artifact.artifact_type == QUALITY_ARTIFACT_TYPE and artifact.data_json),
        None,
    )
    if quality is None or not isinstance(quality.data_json, dict):
        subtitle_quality = next(
            (
                artifact
                for artifact in reversed(artifacts)
                if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT and isinstance(artifact.data_json, dict)
            ),
            None,
        )
        subtitle_term_resolution = next(
            (
                artifact
                for artifact in reversed(artifacts)
                if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH
                and isinstance(artifact.data_json, dict)
            ),
            None,
        )
        subtitle_consistency = next(
            (
                artifact
                for artifact in reversed(artifacts)
                if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
                and isinstance(artifact.data_json, dict)
            ),
            None,
        )
        if subtitle_quality is None and subtitle_term_resolution is None and subtitle_consistency is None:
            return {"score": None, "grade": None, "summary": None, "issue_codes": []}

        subtitle_score: float | None = None
        subtitle_grade: str | None = None
        summary_parts: list[str] = []
        issue_codes: list[str] = []

        if subtitle_quality is not None:
            data = subtitle_quality.data_json
            score_raw = data.get("score")
            try:
                subtitle_score = float(score_raw) if score_raw is not None else None
            except (TypeError, ValueError):
                subtitle_score = None
            blocking = bool(data.get("blocking"))
            blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
            warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
            issue_codes = blocking_reasons or warning_reasons
            if subtitle_score is not None:
                if subtitle_score >= 95:
                    subtitle_grade = "A"
                elif subtitle_score >= 85:
                    subtitle_grade = "B"
                elif subtitle_score >= 70:
                    subtitle_grade = "C"
                else:
                    subtitle_grade = "D"
            summary_parts.append(
                f"字幕质检 {subtitle_grade} {subtitle_score:.1f}"
                if subtitle_grade and subtitle_score is not None
                else (f"字幕质检 {subtitle_score:.1f}" if subtitle_score is not None else "字幕质检")
            )
            if blocking:
                summary_parts.append("已阻断自动放行")
        if subtitle_term_resolution is not None:
            data = subtitle_term_resolution.data_json
            metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
            patch_count = int(metrics.get("patch_count") or 0)
            pending = int(metrics.get("pending_count") or 0)
            auto_applied = int(metrics.get("auto_applied_count") or 0)
            if patch_count or pending or auto_applied:
                summary_parts.append(f"术语解析 {patch_count} 条")
            if pending > 0:
                issue_codes.append(f"术语解析待确认 {pending} 条")
            elif auto_applied > 0:
                issue_codes.append(f"术语解析词级自动接受 {auto_applied} 条")
        if subtitle_consistency is not None:
            data = subtitle_consistency.data_json
            score_raw = data.get("score")
            try:
                consistency_score = float(score_raw) if score_raw is not None else None
            except (TypeError, ValueError):
                consistency_score = None
            blocking = bool(data.get("blocking"))
            blocking_reasons = [str(item).strip() for item in (data.get("blocking_reasons") or []) if str(item).strip()]
            warning_reasons = [str(item).strip() for item in (data.get("warning_reasons") or []) if str(item).strip()]
            if consistency_score is not None and subtitle_score is None:
                subtitle_score = consistency_score
                if subtitle_score >= 95:
                    subtitle_grade = "A"
                elif subtitle_score >= 85:
                    subtitle_grade = "B"
                elif subtitle_score >= 70:
                    subtitle_grade = "C"
                else:
                    subtitle_grade = "D"
            summary_parts.append(
                f"一致性审校 {consistency_score:.1f}"
                if consistency_score is not None
                else "一致性审校"
            )
            if blocking:
                issue_codes.extend(blocking_reasons or ["一致性审校未通过"])
            elif warning_reasons:
                issue_codes.extend(warning_reasons)

        summary = " · ".join(part for part in summary_parts if part).strip() or None
        return {
            "score": subtitle_score,
            "grade": subtitle_grade,
            "summary": summary,
            "issue_codes": issue_codes,
        }

    data = quality.data_json
    score_raw = data.get("score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None
    grade = str(data.get("grade") or "").strip() or None
    issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()]
    manual_review_required = bool(data.get("manual_review_required"))
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    timing_summary = _resolve_variant_timing_summary(bundle)
    validation_summary = _summarize_variant_timeline_validation(bundle)
    summary = " · ".join(
        part
        for part in [
            f"{grade} {score:.1f}" if grade and score is not None else (grade or (f"{score:.1f}" if score is not None else "")),
            f"{len(issue_codes)} 个扣分项" if issue_codes else "",
            "人工复核" if manual_review_required else "",
            timing_summary or "",
            validation_summary or "",
        ]
        if part
    ) or None
    return {
        "score": score,
        "grade": grade,
        "summary": summary,
        "issue_codes": issue_codes,
    }


def _resolve_job_timeline_diagnostics_preview(artifacts: list[Artifact]) -> dict[str, Any] | None:
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    diagnostics = variant_timeline_diagnostics(bundle)
    if not isinstance(diagnostics, dict):
        return None

    review_flags = variant_review_flags(bundle)
    llm_cut_review = variant_llm_cut_review(bundle)
    multimodal_trim_review_summary = variant_multimodal_trim_review_summary(bundle)
    refine_decision_summary = variant_refine_decision_summary(bundle)
    high_risk_cuts = variant_high_risk_cuts(bundle)
    high_energy_keeps = variant_high_energy_keeps(bundle)
    review_reasons = [str(item).strip() for item in (review_flags.get("review_reasons") or []) if str(item).strip()]
    cut_evidence_summary = variant_cut_evidence_summary(bundle)

    preview = {
        "review_recommended": bool(review_flags.get("review_recommended")),
        "review_reasons": review_reasons[:3],
        "high_risk_cut_count": len(high_risk_cuts),
        "high_energy_keep_count": len(high_energy_keeps),
        "protected_visual_cut_count": int(cut_evidence_summary.get("protected_visual_cut_count") or 0),
        "high_protection_evidence_count": int(cut_evidence_summary.get("high_protection_evidence_count") or 0),
        "llm_reviewed": bool(llm_cut_review.get("reviewed")),
        "llm_candidate_count": int(llm_cut_review.get("candidate_count") or 0),
        "llm_restored_cut_count": int(llm_cut_review.get("restored_cut_count") or 0),
        "llm_provider": str(llm_cut_review.get("provider") or "").strip() or None,
        "llm_summary": str(llm_cut_review.get("summary") or "").strip() or None,
        "multimodal_candidate_count": int(multimodal_trim_review_summary.get("candidate_count") or 0),
        "multimodal_accepted_count": int(multimodal_trim_review_summary.get("accepted_count") or 0),
        "multimodal_rejected_count": int(multimodal_trim_review_summary.get("rejected_count") or 0),
        "multimodal_pending_count": int(multimodal_trim_review_summary.get("pending_count") or 0),
        "multimodal_auto_apply_cut_count": int(multimodal_trim_review_summary.get("auto_apply_cut_count") or 0),
        "multimodal_error": str(multimodal_trim_review_summary.get("error") or "").strip() or None,
        "refine_mode": str(refine_decision_summary.get("mode") or "").strip() or None,
        "refine_keep_segment_count": int(refine_decision_summary.get("keep_segment_count") or 0),
        "refine_candidate_total": int(refine_decision_summary.get("candidate_total") or 0),
        "refine_manual_confirm_count": int(refine_decision_summary.get("candidate_manual_confirm") or 0),
    }
    if any(
        (
            preview["review_recommended"],
            preview["high_risk_cut_count"],
            preview["high_energy_keep_count"],
            preview["protected_visual_cut_count"],
            preview["high_protection_evidence_count"],
            preview["llm_reviewed"],
            preview["llm_restored_cut_count"],
            preview["multimodal_candidate_count"],
            preview["multimodal_accepted_count"],
            preview["multimodal_pending_count"],
            preview["multimodal_auto_apply_cut_count"],
            preview["review_reasons"],
            preview["llm_summary"],
            preview["multimodal_error"],
        )
    ):
        return preview
    return None


def _resolve_waiting_review_step(steps: list[JobStep]) -> JobStep | None:
    return next(
        (
            step for step in steps
            if step.step_name == "summary_review" and step.status == "pending"
        ),
        None,
    )


def _review_step_waiting_detail(step_name: str) -> str:
    return "内容异常门发现阻塞问题，处理后继续剪辑与渲染。"


def _pending_step_standard_detail(step_name: str) -> str | None:
    normalized = str(step_name or "").strip().lower()
    if normalized == "summary_review":
        return "等待处理内容异常。"
    return None


def _manual_editor_waiting_detail() -> str:
    return (
        "智能辅助模式已完成剪辑预处理。当前进度仅表示预处理完成度，尚未开始正式渲染；"
        "请打开手动调整后点击“正式渲染/重新渲染”提交。"
    )


def _resolve_manual_editor_waiting_context(job: Job) -> dict[str, str | None]:
    steps = _ordered_steps(job.steps or [])
    render_step = _find_step(steps, "render")
    step_name = "edit_plan"
    detail = ""
    if render_step is not None and render_step.status in {"pending", "running"}:
        detail = str((render_step.metadata_ or {}).get("detail") or "").strip()
    return {
        "step_name": step_name,
        "label": "手动剪辑",
        "detail": detail or _manual_editor_waiting_detail(),
    }


def _resolve_job_review_context(job: Job) -> dict[str, str | None]:
    if str(job.status or "").strip() != "needs_review":
        return {"step_name": None, "label": None, "detail": None}

    steps = _ordered_steps(job.steps or [])
    subtitle_artifacts = select_latest_subtitle_artifact_payloads(list(job.artifacts or []))
    subtitle_review_context = build_subtitle_review_context(
        subtitle_quality_report=subtitle_artifacts.get(ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT),
        subtitle_term_resolution_patch=subtitle_artifacts.get(ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH),
        subtitle_consistency_report=subtitle_artifacts.get(ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT),
        pending_candidate_count=0,
    )
    review_step = _resolve_waiting_review_step(steps)
    if review_step is None:
        summary_review_step = _find_step(steps, "summary_review")
        if summary_review_step is not None and summary_review_step.status != "done":
            review_step = summary_review_step

    if review_step is None:
        if subtitle_review_context["label"]:
            return subtitle_review_context
        return {
            "step_name": "summary_review",
            "label": STEP_LABELS["summary_review"],
            "detail": _review_step_waiting_detail("summary_review"),
        }

    if review_step.step_name == "summary_review" and subtitle_review_context["label"]:
        return subtitle_review_context

    return {
        "step_name": review_step.step_name,
        "label": STEP_LABELS.get(review_step.step_name, review_step.step_name),
        "detail": _review_step_waiting_detail(review_step.step_name),
    }


def _resolve_effective_variant_bundle_from_artifacts(artifacts: list[Artifact]) -> dict[str, Any] | None:
    bundle_artifact = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "variant_timeline_bundle" and artifact.data_json),
        None,
    )
    return resolve_effective_variant_timeline_bundle(
        bundle_artifact.data_json if bundle_artifact and isinstance(bundle_artifact.data_json, dict) else None,
    )


def _resolve_variant_timing_summary(bundle: dict[str, Any] | None) -> str | None:
    if bundle is None or not isinstance(bundle, dict):
        return None
    variants = bundle.get("variants")
    if not isinstance(variants, dict):
        return None
    packaged_variant = variants.get("packaged")
    if not isinstance(packaged_variant, dict):
        return None
    subtitle_events = packaged_variant.get("subtitle_events")
    if not isinstance(subtitle_events, list):
        return None

    event_count = 0
    first_start: float | None = None
    last_end: float | None = None
    for item in subtitle_events:
        if not isinstance(item, dict):
            continue
        event_count += 1
        start_value = _coerce_timing_value(
            item.get("start_time", item.get("start_sec", item.get("start")))
        )
        end_value = _coerce_timing_value(item.get("end_time", item.get("end_sec", item.get("end"))))
        if start_value is not None:
            first_start = start_value if first_start is None else min(first_start, start_value)
        if end_value is not None:
            last_end = end_value if last_end is None else max(last_end, end_value)

    if event_count <= 0:
        return None

    parts = [f"packaged {event_count} 条字幕"]
    if first_start is not None and last_end is not None:
        parts.append(f"{first_start:.1f}-{last_end:.1f}s")
    elif first_start is not None:
        parts.append(f"起始 {first_start:.1f}s")
    elif last_end is not None:
        parts.append(f"结束 {last_end:.1f}s")
    return " · ".join(parts)


def _summarize_variant_timeline_validation(bundle: dict[str, Any] | None) -> str | None:
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    if not isinstance(validation, dict):
        return None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()]
    status = str(validation.get("status") or "").strip().lower()
    if not issues and status in {"", "ok"}:
        return None
    label = "时间轴异常" if status == "error" else "时间轴告警"
    return f"{label} {len(issues)} 项" if issues else label


def _describe_variant_timeline_validation(bundle: dict[str, Any] | None, *, limit: int = 3) -> str | None:
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    if not isinstance(validation, dict):
        return None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()]
    if not issues:
        return None
    visible = issues[:limit]
    if len(issues) > limit:
        visible.append(f"其余 {len(issues) - limit} 项省略")
    return "；".join(visible)


def _coerce_timing_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _select_preview_artifact(artifacts: list[Artifact]) -> Artifact | None:
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.artifact_type in PROFILE_ARTIFACT_PRIORITY and artifact.data_json
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda artifact: (
            PROFILE_ARTIFACT_PRIORITY.get(artifact.artifact_type, 0),
            artifact.created_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return candidates[0]


async def _resolve_job_open_target(job: Job, session: AsyncSession) -> tuple[str | None, str]:
    render_result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job.id, RenderOutput.output_path.is_not(None))
        .order_by(RenderOutput.created_at.desc())
    )
    for item in render_result.scalars().all():
        if not item.output_path:
            continue
        target_path = _resolve_file_manager_existing_path(item.output_path)
        if target_path is not None and can_open_in_file_manager(target_path):
            return str(target_path), "output"

    source_path = _resolve_file_manager_existing_path(job.source_path)
    if source_path is not None and can_open_in_file_manager(source_path):
        return str(source_path), "source"
    return None, "none"


def _resolve_file_manager_existing_path(raw_path: Any) -> Path | str | None:
    path_text = str(raw_path or "").strip().strip('"')
    if not path_text:
        return None

    runtime_path = _first_existing_runtime_path(path_text, file_only=False)
    if runtime_path is not None and can_open_in_file_manager(runtime_path):
        return runtime_path

    candidate = Path(path_text).expanduser()
    try:
        if candidate.exists():
            return candidate.resolve()
    except OSError:
        pass

    if not candidate.is_absolute():
        for base in _file_manager_relative_path_bases():
            resolved = (base / candidate).expanduser()
            try:
                if resolved.exists():
                    return resolved.resolve()
            except OSError:
                pass
            if can_open_in_file_manager(str(resolved)):
                return str(resolved)

    resolve_path = getattr(get_storage(), "resolve_path", None)
    if callable(resolve_path):
        try:
            resolved = resolve_path(path_text)
            if resolved.exists():
                return resolved.resolve()
        except OSError:
            pass

    if can_open_in_file_manager(path_text):
        return path_text
    return None


def _file_manager_relative_path_bases() -> list[Path]:
    bases: list[Path] = [DEFAULT_PROJECT_ROOT]
    host_project_root = _file_manager_host_project_root()
    if host_project_root is not None and host_project_root not in bases:
        bases.append(host_project_root)
    settings = get_settings()
    for raw_base in (
        getattr(settings, "output_dir", None),
        Path(str(getattr(settings, "output_dir", "") or "")).parent if getattr(settings, "output_dir", None) else None,
        getattr(settings, "job_storage_dir", None),
        Path(str(getattr(settings, "job_storage_dir", "") or "")).parent if getattr(settings, "job_storage_dir", None) else None,
    ):
        if not raw_base:
            continue
        try:
            base = Path(str(raw_base)).expanduser()
        except TypeError:
            continue
        if base not in bases:
            bases.append(base)
    return bases


def _file_manager_host_project_root() -> Path | None:
    explicit = str(os.getenv("ROUGHCUT_PROJECT_HOST_ROOT") or os.getenv("ROUGHCUT_WORKSPACE_HOST_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser()

    output_host_root = str(os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT") or "").strip()
    if not output_host_root:
        return None
    root = Path(output_host_root).expanduser()
    normalized_parts = [part.lower() for part in root.parts]
    if len(normalized_parts) >= 2 and normalized_parts[-2:] == ["data", "runtime"]:
        return root.parents[1]
    return None


def _open_in_file_manager(target_path: str | Path) -> None:
    open_in_file_manager(target_path)


async def _ensure_content_profile_thumbnail(job: Job, *, index: int) -> Path:
    cache_dir = _content_profile_thumbnail_cache_dir(job.id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"profile_{index:02d}.jpg"
    if cached.exists() and not _is_content_profile_placeholder_thumbnail(cached):
        return cached

    lock = _CONTENT_PROFILE_THUMBNAIL_LOCKS.setdefault(f"{job.id}:{index}", asyncio.Lock())
    async with lock:
        if cached.exists() and not _is_content_profile_placeholder_thumbnail(cached):
            return cached
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                source_path = await _resolve_job_source(job, tmpdir)
            except FileNotFoundError:
                raise FileNotFoundError(f"Unable to resolve source media for job {job.id}")
            try:
                from roughcut.media.rotation import detect_video_rotation_decision

                orientation_decision = (await detect_video_rotation_decision(source_path)).to_dict()
            except Exception:
                orientation_decision = {}
            loop = asyncio.get_running_loop()
            async with _CONTENT_PROFILE_THUMBNAIL_GENERATION_SEMAPHORE:
                success = await loop.run_in_executor(
                    None,
                    _extract_reference_frame,
                    source_path,
                    cache_dir,
                    index,
                    3,
                    orientation_decision,
                )
            if not success:
                raise RuntimeError(f"Unable to extract content profile thumbnail for job {job.id}")
        if not cached.exists():
            raise RuntimeError(f"Unable to materialize content profile thumbnail for job {job.id}")
    return cached


def _content_profile_thumbnail_cache_dir(job_id: uuid.UUID | str) -> Path:
    return (
        Path(tempfile.gettempdir())
        / "roughcut_content_profile_frames"
        / _CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION
        / str(job_id)
    )


def _clear_content_profile_thumbnail_cache(job_id: uuid.UUID | str) -> None:
    job_id_str = str(job_id)
    prefix = f"{job_id_str}:"
    for key in [key for key in _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS if key.startswith(prefix)]:
        task = _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.pop(key, None)
        if task and not task.done():
            task.cancel()
    for key in [key for key in _CONTENT_PROFILE_THUMBNAIL_LOCKS if key.startswith(prefix)]:
        _CONTENT_PROFILE_THUMBNAIL_LOCKS.pop(key, None)
    shutil.rmtree(_content_profile_thumbnail_cache_dir(job_id_str), ignore_errors=True)


def _spawn_content_profile_thumbnail_generation(job: Job, *, index: int) -> bool:
    key = f"{job.id}:{index}"
    existing = _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.get(key)
    if existing and not existing.done():
        return False

    async def runner() -> bool:
        try:
            await _ensure_content_profile_thumbnail(job, index=index)
        except Exception:
            return False
        return True

    task = asyncio.create_task(runner())
    _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS[key] = task

    def _cleanup(_task: asyncio.Task) -> None:
        _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.pop(key, None)

    task.add_done_callback(_cleanup)
    return True


def _extract_reference_frame(
    source_path: Path,
    cache_dir: Path,
    index: int,
    total_frames: int,
    orientation_decision: dict[str, Any] | None = None,
) -> bool:
    out = cache_dir / f"profile_{index:02d}.jpg"
    out.unlink(missing_ok=True)
    try:
        total_frames = max(1, min(int(total_frames or 1), 10))
        index = max(0, min(int(index or 0), total_frames - 1))
        duration = _probe_duration(source_path)
        if duration <= 0:
            return False

        safe_margin = min(max(duration * 0.08, 1.0), max(duration / 4, 0.0))
        usable_start = safe_margin if duration > safe_margin * 2 else 0.0
        usable_end = duration - safe_margin if duration > safe_margin * 2 else duration
        usable_duration = max(usable_end - usable_start, duration)
        segment_start = usable_start + (usable_duration * index / max(total_frames, 1))
        segment_end = usable_start + (usable_duration * (index + 1) / max(total_frames, 1))
        segment_length = max(segment_end - segment_start, 0.8)
        seek = max(segment_start + (segment_length / 2), 0.0)

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{segment_start:.2f}",
                "-t",
                f"{segment_length:.2f}",
                "-noautorotate",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-vf",
                _content_profile_thumbnail_video_filter(orientation_decision, "thumbnail=90", "scale=960:-2"),
                str(out),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 or not out.exists():
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{seek:.2f}",
                    "-noautorotate",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    "-q:v",
                    "3",
                    "-vf",
                    _content_profile_thumbnail_video_filter(orientation_decision, "scale=960:-2"),
                    str(out),
                ],
                capture_output=True,
                timeout=20,
            )
        return result.returncode == 0 and out.exists()
    except Exception:
        return False


def _content_profile_thumbnail_video_filter(
    orientation_decision: dict[str, Any] | None,
    *extra_filters: str,
) -> str:
    from roughcut.media.rotation import build_orientation_video_filter

    return build_orientation_video_filter(orientation_decision, *extra_filters)



async def _resolve_job_source(job: Job, tmpdir: str) -> Path:
    storage = get_storage()
    candidate_keys = [
        str(job.source_path or "").strip(),
        job_key(str(job.id), "output_plain.mp4"),
        job_key(str(job.id), "output.mp4"),
        job_key(str(job.id), "output_ai_effect.mp4"),
    ]
    resolve_path = getattr(storage, "resolve_path", None)

    for candidate_key in candidate_keys:
        if not candidate_key:
            continue
        if callable(resolve_path):
            resolved = resolve_path(candidate_key)
            if resolved.exists() and resolved.is_file():
                return resolved
        local_name = Path(str(candidate_key).replace("s3://", "", 1)).name or job.source_name
        local_path = Path(tmpdir) / local_name
        try:
            await storage.async_download_file(candidate_key, local_path)
        except FileNotFoundError:
            continue
        if local_path.exists():
            return local_path

    raise FileNotFoundError(f"Unable to resolve source media for job {job.id}")


def _write_content_profile_placeholder_thumbnail(job: Job, target_path: Path, *, index: int) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(_CONTENT_PROFILE_PLACEHOLDER_JPEG)


def _is_content_profile_placeholder_thumbnail(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes() == _CONTENT_PROFILE_PLACEHOLDER_JPEG
    except OSError:
        return False


def _should_retry_placeholder_thumbnail(path: Path) -> bool:
    if not path.exists():
        return True
    if not _is_content_profile_placeholder_thumbnail(path):
        return False
    try:
        age_seconds = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return True
    return age_seconds >= _CONTENT_PROFILE_PLACEHOLDER_RETRY_SECONDS


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
