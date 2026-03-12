from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from roughcut.api.options import normalize_channel_profile, normalize_job_language


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    language: str = "zh-CN"
    channel_profile: str | None = None

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, value: Any) -> str:
        return normalize_job_language(value)

    @field_validator("channel_profile", mode="before")
    @classmethod
    def validate_channel_profile(cls, value: Any) -> str | None:
        return normalize_channel_profile(value)


class JobStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_name: str
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    content_subject: str | None = None
    content_summary: str | None = None
    status: str
    language: str
    channel_profile: str | None
    file_hash: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[JobStepOut] = []


class JobActivityCurrentStepOut(BaseModel):
    step_name: str
    label: str
    status: str
    detail: str | None = None
    progress: float | None = None
    updated_at: str | None = None


class JobActivityDecisionOut(BaseModel):
    kind: str
    title: str
    status: str
    summary: str
    detail: str | None = None
    updated_at: str | None = None


class JobActivityEventOut(BaseModel):
    timestamp: str
    type: str
    status: str
    title: str
    detail: str | None = None


class JobActivityRenderOut(BaseModel):
    status: str
    progress: float
    output_path: str | None = None
    updated_at: str | None = None


class JobActivityOut(BaseModel):
    job_id: str
    status: str
    current_step: JobActivityCurrentStepOut | None = None
    render: JobActivityRenderOut | None = None
    decisions: list[JobActivityDecisionOut]
    events: list[JobActivityEventOut]


class ContentProfileReviewOut(BaseModel):
    job_id: str
    status: str
    review_step_status: str
    draft: dict[str, Any] | None
    final: dict[str, Any] | None
    memory: dict[str, Any] | None = None


class OpenFolderOut(BaseModel):
    path: str
    kind: str


class ContentProfileMemoryStatsOut(BaseModel):
    scope: str
    channel_profile: str | None = None
    channel_profiles: list[str] = []
    total_corrections: int = 0
    total_keywords: int = 0
    field_preferences: dict[str, list[dict[str, Any]]] = {}
    keyword_preferences: list[dict[str, Any]] = []
    recent_corrections: list[dict[str, Any]] = []
    cloud: dict[str, Any] = {}


class ContentProfileConfirmIn(BaseModel):
    subject_brand: str | None = None
    subject_model: str | None = None
    subject_type: str | None = None
    video_theme: str | None = None
    hook_line: str | None = None
    visible_text: str | None = None
    summary: str | None = None
    engagement_question: str | None = None
    keywords: list[str] | None = None
    correction_notes: str | None = None
    supplemental_context: str | None = None


class PackagingAssetOut(BaseModel):
    id: str
    asset_type: str
    original_name: str
    stored_name: str
    path: str
    size_bytes: int
    content_type: str
    created_at: str


class PackagingConfigOut(BaseModel):
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    insert_asset_id: str | None = None
    insert_asset_ids: list[str] = []
    insert_selection_mode: str = "manual"
    insert_position_mode: str = "llm"
    watermark_asset_id: str | None = None
    music_asset_ids: list[str] = []
    music_selection_mode: str = "random"
    music_loop_mode: str = "loop_single"
    subtitle_style: str = "bold_yellow_outline"
    cover_style: str = "preset_default"
    title_style: str = "preset_default"
    music_volume: float = 0.22
    watermark_position: str = "top_right"
    watermark_opacity: float = 0.82
    watermark_scale: float = 0.16
    enabled: bool = True


class PackagingLibraryOut(BaseModel):
    assets: dict[str, list[PackagingAssetOut]]
    config: PackagingConfigOut


class PackagingConfigPatch(BaseModel):
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    insert_asset_id: str | None = None
    insert_asset_ids: list[str] | None = None
    insert_selection_mode: str | None = None
    insert_position_mode: str | None = None
    watermark_asset_id: str | None = None
    music_asset_ids: list[str] | None = None
    music_selection_mode: str | None = None
    music_loop_mode: str | None = None
    subtitle_style: str | None = None
    cover_style: str | None = None
    title_style: str | None = None
    music_volume: float | None = None
    watermark_position: str | None = None
    watermark_opacity: float | None = None
    watermark_scale: float | None = None
    enabled: bool | None = None


# ── Glossary ──────────────────────────────────────────────────────────────────

class GlossaryTermCreate(BaseModel):
    wrong_forms: list[str] = Field(min_length=1)
    correct_form: str
    category: str | None = None
    context_hint: str | None = None


class GlossaryTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wrong_forms: list[str]
    correct_form: str
    category: str | None
    context_hint: str | None
    created_at: datetime


class GlossaryTermUpdate(BaseModel):
    wrong_forms: list[str] | None = None
    correct_form: str | None = None
    category: str | None = None
    context_hint: str | None = None


# ── Watch Roots ───────────────────────────────────────────────────────────────

class WatchRootCreate(BaseModel):
    path: str
    channel_profile: str | None = None
    enabled: bool = True
    scan_mode: Literal["fast", "precise"] = "fast"

    @field_validator("channel_profile", mode="before")
    @classmethod
    def validate_channel_profile(cls, value: Any) -> str | None:
        return normalize_channel_profile(value)


class WatchRootOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    channel_profile: str | None
    enabled: bool
    scan_mode: Literal["fast", "precise"]
    created_at: datetime


class WatchInventoryItemOut(BaseModel):
    path: str
    relative_path: str
    source_name: str
    stem: str
    size_bytes: int
    modified_at: str
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    status: str
    dedupe_reason: str | None = None
    matched_job_id: str | None = None
    matched_output_path: str | None = None


class WatchInventoryOut(BaseModel):
    pending: list[WatchInventoryItemOut]
    deduped: list[WatchInventoryItemOut]


class WatchInventoryScanIn(BaseModel):
    force: bool = False


class WatchInventoryEnqueueIn(BaseModel):
    relative_paths: list[str] = Field(default_factory=list)
    enqueue_all: bool = False


class WatchInventoryEnqueueOut(BaseModel):
    requested_count: int
    created_count: int
    skipped_count: int
    created_job_ids: list[str]


class WatchInventoryScanStatusOut(BaseModel):
    root_path: str
    scan_mode: Literal["fast", "precise"]
    status: str
    started_at: str
    updated_at: str
    finished_at: str | None = None
    total_files: int
    processed_files: int
    pending_count: int
    deduped_count: int
    current_file: str | None = None
    current_phase: str | None = None
    current_file_size_bytes: int | None = None
    current_file_processed_bytes: int | None = None
    error: str | None = None
    inventory: WatchInventoryOut


# ── Review ────────────────────────────────────────────────────────────────────

class ReviewActionCreate(BaseModel):
    target_type: str  # subtitle_correction | fact_claim | edit_decision
    target_id: uuid.UUID
    action: str  # accept | reject | modify
    override_text: str | None = None


class ReviewApplyRequest(BaseModel):
    actions: list[ReviewActionCreate]


# ── Report ────────────────────────────────────────────────────────────────────

class CorrectionItem(BaseModel):
    id: str
    original: str
    suggested: str
    type: str
    confidence: float
    source: str | None
    decision: str | None
    override: str | None


class SubtitleReportItem(BaseModel):
    index: int
    start: float
    end: float
    text_raw: str
    text_norm: str | None
    text_final: str | None
    corrections: list[CorrectionItem]


class ReportOut(BaseModel):
    job_id: str
    generated_at: str
    total_subtitle_items: int
    total_corrections: int
    corrections_by_type: dict[str, int]
    pending_count: int
    accepted_count: int
    rejected_count: int
    items: list[Any]
