from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from roughcut.creative.modes import (
    DEFAULT_WORKFLOW_MODE,
    normalize_enhancement_modes,
    normalize_workflow_mode,
)
from roughcut.api.options import normalize_job_language, normalize_workflow_template


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    language: str = "zh-CN"
    workflow_template: str | None = None
    workflow_mode: str = DEFAULT_WORKFLOW_MODE
    enhancement_modes: list[str] = Field(default_factory=list)
    output_dir: str | None = None
    video_description: str | None = None

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, value: Any) -> str:
        return normalize_job_language(value)

    @field_validator("workflow_template", mode="before")
    @classmethod
    def validate_workflow_template(cls, value: Any) -> str | None:
        return normalize_workflow_template(value)

    @field_validator("workflow_mode", mode="before")
    @classmethod
    def validate_workflow_mode(cls, value: Any) -> str:
        return normalize_workflow_mode(str(value or DEFAULT_WORKFLOW_MODE))

    @field_validator("enhancement_modes", mode="before")
    @classmethod
    def validate_enhancement_modes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return normalize_enhancement_modes([item for item in value.split(",") if item.strip()])
        if isinstance(value, (list, tuple, set)):
            return normalize_enhancement_modes(list(value))
        raise ValueError("enhancement_modes must be a list of strings")

    @field_validator("output_dir", mode="before")
    @classmethod
    def validate_output_dir(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("video_description", mode="before")
    @classmethod
    def validate_video_description(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized[:4000] or None


class JobInitializeIn(JobCreate):
    video_description: str

    @field_validator("video_description", mode="before")
    @classmethod
    def require_video_description(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("video_description is required")
        return normalized[:4000]


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
    merged_source_names: list[str] = Field(default_factory=list)
    video_description: str | None = None
    content_subject: str | None = None
    content_summary: str | None = None
    quality_score: float | None = None
    quality_grade: str | None = None
    quality_summary: str | None = None
    quality_issue_codes: list[str] = Field(default_factory=list)
    timeline_diagnostics: dict[str, Any] | None = None
    avatar_delivery_status: str | None = None
    avatar_delivery_summary: str | None = None
    status: str
    language: str
    workflow_template: str | None
    output_dir: str | None
    workflow_mode: str
    enhancement_modes: list[str] = Field(default_factory=list)
    auto_review_mode_enabled: bool = False
    auto_review_status: str | None = None
    auto_review_summary: str | None = None
    auto_review_reasons: list[str] = Field(default_factory=list)
    review_step: Literal["summary_review", "final_review"] | None = None
    review_label: str | None = None
    review_detail: str | None = None
    awaiting_initialization: bool = False
    file_hash: str | None
    error_message: str | None
    progress_percent: int = 0
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
    step_name: str | None = None
    title: str
    status: str
    summary: str
    detail: str | None = None
    blocking: bool | None = None
    review_route: str | None = None
    review_label: str | None = None
    recommended_action: str | None = None
    rerun_start_step: str | None = None
    rerun_steps: list[str] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class JobActivityEventOut(BaseModel):
    timestamp: str
    type: str
    status: str
    step_name: str | None = None
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
    review_step: Literal["summary_review", "final_review"] | None = None
    review_detail: str | None = None
    current_step: JobActivityCurrentStepOut | None = None
    render: JobActivityRenderOut | None = None
    decisions: list[JobActivityDecisionOut]
    events: list[JobActivityEventOut]


class TokenUsageOperationOut(BaseModel):
    operation: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TokenUsageBaselineOut(BaseModel):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TokenUsageCacheEntryOut(BaseModel):
    name: str
    namespace: str = ""
    key: str = ""
    hit: bool = False
    usage_baseline: TokenUsageBaselineOut | None = None


class TokenUsageCacheSummaryOut(BaseModel):
    total_entries: int = 0
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    avoided_calls: int = 0
    steps_with_hits: int = 0
    hits_with_usage_baseline: int = 0
    saved_prompt_tokens: int = 0
    saved_completion_tokens: int = 0
    saved_total_tokens: int = 0
    saved_tokens_hit_rate: float = 0.0


class TokenUsageStepOut(BaseModel):
    step_name: str
    label: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last_updated_at: str | None = None
    operations: list[TokenUsageOperationOut] = []
    cache_entries: list[TokenUsageCacheEntryOut] = []


class TokenUsageModelOut(BaseModel):
    model: str
    provider: str | None = None
    kind: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TokenUsageReportOut(BaseModel):
    job_id: str
    has_telemetry: bool = False
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    steps: list[TokenUsageStepOut] = []
    models: list[TokenUsageModelOut] = []
    cache: TokenUsageCacheSummaryOut = Field(default_factory=TokenUsageCacheSummaryOut)


class JobsUsageSummaryStepOut(BaseModel):
    step_name: str
    label: str
    jobs: int = 0
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class JobsUsageSummaryModelOut(BaseModel):
    model: str
    provider: str | None = None
    kind: str | None = None
    jobs: int = 0
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class JobsUsageSummaryProviderOut(BaseModel):
    provider: str
    jobs: int = 0
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class JobsUsageSummaryOut(BaseModel):
    job_count: int = 0
    jobs_with_telemetry: int = 0
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    cache: TokenUsageCacheSummaryOut = Field(default_factory=TokenUsageCacheSummaryOut)
    top_steps: list[JobsUsageSummaryStepOut] = []
    top_models: list[JobsUsageSummaryModelOut] = []
    top_providers: list[JobsUsageSummaryProviderOut] = []


class JobsUsageTrendPointTopStepOut(BaseModel):
    step_name: str
    label: str
    total_tokens: int = 0


class JobsUsageTrendPointTopEntryOut(BaseModel):
    dimension: str
    name: str
    label: str
    total_tokens: int = 0


class JobsUsageTrendPointOut(BaseModel):
    date: str
    label: str
    job_count: int = 0
    jobs_with_telemetry: int = 0
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    cache: TokenUsageCacheSummaryOut = Field(default_factory=TokenUsageCacheSummaryOut)
    top_entry: JobsUsageTrendPointTopEntryOut | None = None
    top_step: JobsUsageTrendPointTopStepOut | None = None


class JobsUsageTrendOut(BaseModel):
    days: int = 7
    focus_type: str | None = None
    focus_name: str | None = None
    points: list[JobsUsageTrendPointOut] = []


class ContentProfileReviewOut(BaseModel):
    job_id: str
    status: str
    review_step_status: str
    review_step_detail: str | None = None
    review_reasons: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    identity_review: dict[str, Any] | None = None
    ocr_evidence: dict[str, Any] = Field(default_factory=dict)
    transcript_evidence: dict[str, Any] = Field(default_factory=dict)
    entity_resolution_trace: dict[str, Any] = Field(default_factory=dict)
    workflow_mode: str
    enhancement_modes: list[str] = Field(default_factory=list)
    draft: dict[str, Any] | None
    final: dict[str, Any] | None
    memory: dict[str, Any] | None = None


class ContentUnderstandingOut(BaseModel):
    video_type: str = ""
    content_domain: str = ""
    primary_subject: str = ""
    subject_entities: list[dict[str, Any]] = Field(default_factory=list)
    video_theme: str = ""
    summary: str = ""
    hook_line: str = ""
    engagement_question: str = ""
    search_queries: list[str] = Field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    needs_review: bool = True
    review_reasons: list[str] = Field(default_factory=list)


class OpenFolderOut(BaseModel):
    path: str
    kind: str


class IntelligentCopyInspectIn(BaseModel):
    folder_path: str


class IntelligentCopyGenerateIn(BaseModel):
    folder_path: str
    copy_style: str | None = None


class IntelligentCopyCoverSizeOut(BaseModel):
    width: int
    height: int


class IntelligentCopyPlatformConstraintsOut(BaseModel):
    title_limit: int
    body_limit: int
    tag_limit: int
    tag_style: str
    cover_size: IntelligentCopyCoverSizeOut
    rule_note: str


class IntelligentCopyPlatformMaterialOut(BaseModel):
    key: str
    label: str
    has_title: bool = True
    title_label: str = "标题"
    body_label: str
    tag_label: str
    constraints: IntelligentCopyPlatformConstraintsOut
    titles: list[str] = []
    primary_title: str = ""
    title_copy_all: str = ""
    body: str = ""
    tags: list[str] = []
    tags_copy: str = ""
    full_copy: str = ""
    cover_path: str | None = None


class IntelligentCopyInspectOut(BaseModel):
    folder_path: str
    material_dir: str
    video_file: str | None = None
    subtitle_file: str | None = None
    cover_file: str | None = None
    extra_video_files: list[str] = []
    extra_subtitle_files: list[str] = []
    extra_cover_files: list[str] = []
    warnings: list[str] = []


class IntelligentCopyResultOut(BaseModel):
    folder_path: str
    material_dir: str
    markdown_path: str
    json_path: str
    copy_style: str
    inspection: IntelligentCopyInspectOut
    highlights: dict[str, Any] = {}
    content_profile_summary: dict[str, Any] = {}
    platforms: list[IntelligentCopyPlatformMaterialOut] = []
    warnings: list[str] = []


class ContentProfileMemoryStatsOut(BaseModel):
    scope: str
    subject_domain: str | None = None
    subject_domains: list[str] = []
    total_corrections: int = 0
    total_keywords: int = 0
    total_learned_hotwords: int = 0
    field_preferences: dict[str, list[dict[str, Any]]] = {}
    keyword_preferences: list[dict[str, Any]] = []
    learned_hotwords: list[dict[str, Any]] = []
    recent_corrections: list[dict[str, Any]] = []
    cloud: dict[str, Any] = {}


class ContentProfileApprovalStatsOut(BaseModel):
    updated_at: str | None = None
    auto_review_enabled: bool
    review_threshold: float
    required_accuracy: float
    minimum_sample_size: int
    gate_passed: bool
    detail: str
    measured_accuracy: float | None = None
    sample_size: int = 0
    manual_review_total: int = 0
    approved_without_changes: int = 0
    corrected_after_review: int = 0
    eligible_manual_review_total: int = 0
    eligible_approved_without_changes: int = 0
    eligible_corrected_after_review: int = 0
    eligible_approval_accuracy: float | None = None


class ContentProfileConfirmIn(BaseModel):
    workflow_mode: str | None = None
    enhancement_modes: list[str] | None = None
    copy_style: str | None = None
    video_type: str | None = None
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

    @field_validator("workflow_mode", mode="before")
    @classmethod
    def validate_optional_workflow_mode(cls, value: Any) -> str | None:
        if value is None:
            return None
        return normalize_workflow_mode(str(value or DEFAULT_WORKFLOW_MODE))

    @field_validator("enhancement_modes", mode="before")
    @classmethod
    def validate_optional_enhancement_modes(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return normalize_enhancement_modes([item for item in value.split(",") if item.strip()])
        if isinstance(value, (list, tuple, set)):
            return normalize_enhancement_modes(list(value))
        raise ValueError("enhancement_modes must be a list of strings")


class PackagingAssetOut(BaseModel):
    id: str
    asset_type: str
    original_name: str
    stored_name: str
    path: str
    size_bytes: int
    content_type: str
    watermark_preprocessed: bool | None = None
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
    subtitle_motion_style: str = "motion_static"
    smart_effect_style: str = "smart_effect_commercial"
    cover_style: str = "preset_default"
    title_style: str = "preset_default"
    copy_style: str = "attention_grabbing"
    music_volume: float = 0.12
    watermark_position: str = "top_left"
    watermark_opacity: float = 0.82
    watermark_scale: float = 0.16
    avatar_overlay_position: str = "top_right"
    avatar_overlay_scale: float = 0.18
    avatar_overlay_corner_radius: int = 26
    avatar_overlay_border_width: int = 4
    avatar_overlay_border_color: str = "#F4E4B8"
    export_resolution_mode: str = "source"
    export_resolution_preset: str = "1080p"
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
    subtitle_motion_style: str | None = None
    smart_effect_style: str | None = None
    cover_style: str | None = None
    title_style: str | None = None
    copy_style: str | None = None
    music_volume: float | None = None
    watermark_position: str | None = None
    watermark_opacity: float | None = None
    watermark_scale: float | None = None
    avatar_overlay_position: str | None = None
    avatar_overlay_scale: float | None = None
    avatar_overlay_corner_radius: int | None = None
    avatar_overlay_border_width: int | None = None
    avatar_overlay_border_color: str | None = None
    export_resolution_mode: str | None = None
    export_resolution_preset: str | None = None
    enabled: bool | None = None


# ── Avatar Materials ──────────────────────────────────────────────────────────

class AvatarMaterialRuleOut(BaseModel):
    severity: str
    title: str
    detail: str


class AvatarMaterialSectionOut(BaseModel):
    title: str
    rules: list[AvatarMaterialRuleOut]


class AvatarMaterialFileOut(BaseModel):
    id: str
    original_name: str
    stored_name: str
    kind: str
    role: str
    role_label: str
    pipeline_target: str
    content_type: str
    size_bytes: int
    path: str
    created_at: str
    probe: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None
    checks: list[dict[str, str]] = []


class AvatarMaterialPreviewRunOut(BaseModel):
    id: str
    status: str
    script: str
    task_code: str | None = None
    source_voice_file_id: str | None = None
    source_video_file_id: str | None = None
    output_path: str | None = None
    output_size_bytes: int | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    preview_mode: str | None = None
    fallback_reason: str | None = None
    error_message: str | None = None
    created_at: str


class AvatarMaterialProfileOut(BaseModel):
    id: str
    display_name: str
    presenter_alias: str | None = None
    notes: str | None = None
    personal_info: dict[str, Any] = {}
    creator_profile: dict[str, Any] = {}
    profile_dashboard: dict[str, Any] = {}
    profile_dir: str
    training_status: str
    training_provider: str
    training_api_available: bool
    next_action: str
    capability_status: dict[str, str] = {}
    blocking_issues: list[str] = []
    warnings: list[str] = []
    created_at: str
    files: list[AvatarMaterialFileOut] = []
    preview_runs: list[AvatarMaterialPreviewRunOut] = []


class AvatarMaterialLibraryOut(BaseModel):
    provider: str
    training_api_available: bool
    preview_service_available: bool = True
    intake_mode: str
    warnings: list[str] = []
    summary: str
    sections: list[AvatarMaterialSectionOut]
    profiles: list[AvatarMaterialProfileOut]


# ── Glossary ──────────────────────────────────────────────────────────────────

class GlossaryTermCreate(BaseModel):
    wrong_forms: list[str] = Field(min_length=1)
    correct_form: str
    scope_type: str = "global"
    scope_value: str = ""
    category: str | None = None
    context_hint: str | None = None


class GlossaryTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope_type: str
    scope_value: str
    wrong_forms: list[str]
    correct_form: str
    category: str | None
    context_hint: str | None
    created_at: datetime


class GlossaryTermUpdate(BaseModel):
    scope_type: str | None = None
    scope_value: str | None = None
    wrong_forms: list[str] | None = None
    correct_form: str | None = None
    category: str | None = None
    context_hint: str | None = None


class BuiltinGlossaryTermOut(BaseModel):
    correct_form: str
    wrong_forms: list[str] = []
    category: str | None = None
    context_hint: str | None = None


class BuiltinGlossaryPackOut(BaseModel):
    domain: str
    presets: list[str] = []
    term_count: int
    terms: list[BuiltinGlossaryTermOut] = []


# ── Learned Hotwords ─────────────────────────────────────────────────────────

class LearnedHotwordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_domain: str
    term: str
    canonical_form: str
    aliases: list[str] = []
    source: str
    status: str
    evidence_count: int
    positive_count: int
    negative_count: int
    prompt_count: int
    confidence: float
    metadata_json: dict[str, Any] | None = None
    last_seen_at: datetime | None = None
    last_prompted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class LearnedHotwordUpdate(BaseModel):
    status: Literal["active", "suppressed", "rejected"] | None = None
    aliases: list[str] | None = None
    confidence: float | None = None


# ── Watch Roots ───────────────────────────────────────────────────────────────

class WatchRootCreate(BaseModel):
    path: str
    config_profile_id: uuid.UUID | None = None
    workflow_template: str | None = None
    output_dir: str | None = None
    enabled: bool = True
    scan_mode: Literal["fast", "precise"] = "fast"
    ingest_mode: Literal["task_only", "full_auto"] = "full_auto"

    @field_validator("config_profile_id", mode="before")
    @classmethod
    def validate_config_profile_id(cls, value: Any) -> uuid.UUID | None:
        if value is None or str(value).strip() == "":
            return None
        return uuid.UUID(str(value))

    @field_validator("workflow_template", mode="before")
    @classmethod
    def validate_workflow_template(cls, value: Any) -> str | None:
        return normalize_workflow_template(value)

    @field_validator("output_dir", mode="before")
    @classmethod
    def validate_output_dir(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class WatchRootOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    config_profile_id: uuid.UUID | None
    workflow_template: str | None
    output_dir: str | None
    enabled: bool
    scan_mode: Literal["fast", "precise"]
    ingest_mode: Literal["task_only", "full_auto"]
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


class WatchInventoryMergeIn(BaseModel):
    relative_paths: list[str] = Field(default_factory=list)


class WatchInventoryEnqueueOut(BaseModel):
    requested_count: int
    created_count: int
    skipped_count: int
    created_job_ids: list[str]


class WatchInventorySmartMergeGroupOut(BaseModel):
    relative_paths: list[str]
    score: float
    reasons: list[str] = []


class WatchInventorySmartMergeOut(BaseModel):
    source_count: int
    groups: list[WatchInventorySmartMergeGroupOut]


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
