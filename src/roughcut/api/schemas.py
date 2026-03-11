from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    language: str = "zh-CN"
    channel_profile: str | None = None


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
    status: str
    language: str
    channel_profile: str | None
    file_hash: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    steps: list[JobStepOut] = []


class ContentProfileReviewOut(BaseModel):
    job_id: str
    status: str
    review_step_status: str
    draft: dict[str, Any] | None
    final: dict[str, Any] | None


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


class WatchRootOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    channel_profile: str | None
    enabled: bool
    created_at: datetime


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
