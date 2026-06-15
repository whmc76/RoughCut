from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from roughcut.db.session import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)

UUID_TYPE = Uuid(as_uuid=True)
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
STRING_LIST_TYPE = JSON().with_variant(ARRAY(Text()), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    workflow_template: Mapped[str | None] = mapped_column(Text)
    output_dir: Mapped[str | None] = mapped_column(Text)
    job_flow_mode: Mapped[str] = mapped_column(Text, nullable=False, default="auto", server_default="auto")
    config_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("config_profiles.id", ondelete="SET NULL"))
    creator_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_cards.id", ondelete="SET NULL"),
    )
    task_brief: Mapped[str | None] = mapped_column(Text)
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, default="auto", server_default="auto")
    platform_targets_json: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list, server_default="[]")
    config_profile_snapshot_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    packaging_snapshot_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    language: Mapped[str] = mapped_column(Text, default="zh-CN")
    workflow_mode: Mapped[str] = mapped_column(Text, nullable=False, default="standard_edit", server_default="standard_edit")
    enhancement_modes: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    steps: Mapped[list[JobStep]] = relationship("JobStep", back_populates="job", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship("Artifact", back_populates="job", cascade="all, delete-orphan")
    transcript_segments: Mapped[list[TranscriptSegment]] = relationship(
        "TranscriptSegment", back_populates="job", cascade="all, delete-orphan"
    )
    subtitle_items: Mapped[list[SubtitleItem]] = relationship(
        "SubtitleItem", back_populates="job", cascade="all, delete-orphan"
    )
    timelines: Mapped[list[Timeline]] = relationship("Timeline", back_populates="job", cascade="all, delete-orphan")
    render_outputs: Mapped[list[RenderOutput]] = relationship(
        "RenderOutput", back_populates="job", cascade="all, delete-orphan"
    )
    publication_attempts: Mapped[list[PublicationAttempt]] = relationship(
        "PublicationAttempt", back_populates="job", cascade="all, delete-orphan"
    )
    creator_card: Mapped[CreatorCard | None] = relationship("CreatorCard", back_populates="jobs")
    agent_plan: Mapped[JobAgentPlan | None] = relationship(
        "JobAgentPlan",
        back_populates="job",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def platform_targets(self) -> list[str]:
        return list(self.platform_targets_json or [])

class JobStep(Base):
    __tablename__ = "job_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON_TYPE)

    job: Mapped[Job] = relationship("Job", back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    step_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("job_steps.id"))
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text)
    data_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="artifacts")
    step: Mapped[JobStep | None] = relationship("JobStep")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    speaker: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words_json: Mapped[list | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="transcript_segments")


class SubtitleItem(Base):
    __tablename__ = "subtitle_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text_raw: Mapped[str] = mapped_column(Text, nullable=False)
    text_norm: Mapped[str | None] = mapped_column(Text)
    text_final: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="subtitle_items")
    corrections: Mapped[list[SubtitleCorrection]] = relationship(
        "SubtitleCorrection", back_populates="subtitle_item", cascade="all, delete-orphan"
    )


class SubtitleCorrection(Base):
    __tablename__ = "subtitle_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    subtitle_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("subtitle_items.id")
    )
    original_span: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_span: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    auto_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    human_decision: Mapped[str | None] = mapped_column(Text)
    human_override: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    subtitle_item: Mapped[SubtitleItem | None] = relationship("SubtitleItem", back_populates="corrections")


# Phase 2 — fact checking tables
class FactClaim(Base):
    __tablename__ = "fact_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    subtitle_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("subtitle_items.id")
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    human_decision: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    evidence: Mapped[list[FactEvidence]] = relationship(
        "FactEvidence", back_populates="claim", cascade="all, delete-orphan"
    )


class FactEvidence(Base):
    __tablename__ = "fact_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("fact_claims.id", ondelete="CASCADE"))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    supports_claim: Mapped[bool | None] = mapped_column(Boolean)
    source_rank: Mapped[int | None] = mapped_column(Integer)
    cached_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    claim: Mapped[FactClaim] = relationship("FactClaim", back_populates="evidence")


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    timeline_type: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    otio_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="timelines")
    render_outputs: Mapped[list[RenderOutput]] = relationship("RenderOutput", back_populates="timeline")


class RenderOutput(Base):
    __tablename__ = "render_outputs"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    timeline_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("timelines.id"))
    output_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="render_outputs")
    timeline: Mapped[Timeline | None] = relationship("Timeline", back_populates="render_outputs")


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    content_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creator_profile_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    creator_profile_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    platform_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    account_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    credential_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    semantic_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    adapter: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    run_status: Mapped[str | None] = mapped_column(Text)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    external_receipt_id: Mapped[str | None] = mapped_column(Text)
    external_post_id: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    request_payload: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    response_payload: Mapped[dict | None] = mapped_column(JSON_TYPE)
    next_retry_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    scheduled_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    submitted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, default="browser_agent")
    content_kind: Mapped[str] = mapped_column(Text, nullable=False, default="video")
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    provider_execution_id: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str | None] = mapped_column(Text)
    operator_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="publication_attempts")
    runs: Mapped[list[PublicationAttemptRun]] = relationship(
        "PublicationAttemptRun", back_populates="attempt", cascade="all, delete-orphan"
    )


class PublicationAttemptRun(Base):
    __tablename__ = "publication_attempt_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    attempt_id: Mapped[str] = mapped_column(Text, ForeignKey("publication_attempts.id", ondelete="CASCADE"))
    content_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform: Mapped[str] = mapped_column(Text, nullable=False, default="")
    adapter: Mapped[str] = mapped_column(Text, nullable=False, default="")
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_kind: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    phase: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    provider_task_id: Mapped[str | None] = mapped_column(Text)
    provider_execution_id: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    attempt: Mapped[PublicationAttempt] = relationship("PublicationAttempt", back_populates="runs")


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    override_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class ContentProfileCorrection(Base):
    __tablename__ = "content_profile_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    subject_domain: Mapped[str | None] = mapped_column(Text)
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text)
    corrected_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

class ContentProfileKeywordStat(Base):
    __tablename__ = "content_profile_keyword_stats"
    __table_args__ = (UniqueConstraint("scope_type", "scope_value", "keyword"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False, default="global")
    scope_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())


class LearnedHotword(Base):
    __tablename__ = "learned_hotwords"
    __table_args__ = (UniqueConstraint("subject_domain", "term", "canonical_form", "source"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    subject_domain: Mapped[str] = mapped_column(Text, nullable=False, default="")
    term: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_form: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="content_profile_feedback")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    metadata_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())
    last_prompted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())


class ContentProfileEntity(Base):
    __tablename__ = "content_profile_entities"
    __table_args__ = (UniqueConstraint("subject_domain", "brand", "model"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    subject_domain: Mapped[str] = mapped_column(Text, nullable=False, default="")
    brand: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    aliases: Mapped[list[ContentProfileEntityAlias]] = relationship(
        "ContentProfileEntityAlias",
        back_populates="entity",
        cascade="all, delete-orphan",
    )
    observations: Mapped[list[ContentProfileEntityObservation]] = relationship(
        "ContentProfileEntityObservation",
        back_populates="entity",
        cascade="all, delete-orphan",
    )


class ContentProfileEntityAlias(Base):
    __tablename__ = "content_profile_entity_aliases"
    __table_args__ = (UniqueConstraint("entity_id", "field_name", "alias_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("content_profile_entities.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    alias_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    entity: Mapped[ContentProfileEntity] = relationship("ContentProfileEntity", back_populates="aliases")


class ContentProfileEntityObservation(Base):
    __tablename__ = "content_profile_entity_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("content_profile_entities.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="SET NULL"))
    source_name: Mapped[str | None] = mapped_column(Text)
    observation_type: Mapped[str] = mapped_column(Text, nullable=False, default="manual_confirm")
    payload_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    entity: Mapped[ContentProfileEntity] = relationship("ContentProfileEntity", back_populates="observations")


class ContentProfileEntityRejection(Base):
    __tablename__ = "content_profile_entity_rejections"
    __table_args__ = (
        UniqueConstraint("subject_domain", "field_name", "alias_value", "canonical_value", "override_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="SET NULL"))
    subject_domain: Mapped[str] = mapped_column(Text, nullable=False, default="")
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    alias_value: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    override_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class WatchRoot(Base):
    __tablename__ = "watch_roots"
    __table_args__ = (UniqueConstraint("path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    config_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("config_profiles.id", ondelete="SET NULL"))
    workflow_template: Mapped[str | None] = mapped_column(Text)
    output_dir: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    scan_mode: Mapped[str] = mapped_column(Text, nullable=False, default="fast", server_default="fast")
    ingest_mode: Mapped[str] = mapped_column(Text, nullable=False, default="full_auto", server_default="full_auto")
    job_flow_mode: Mapped[str] = mapped_column(Text, nullable=False, default="auto", server_default="auto")
    inventory_cache_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    inventory_cache_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False, default="global")
    scope_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wrong_forms: Mapped[list[str]] = mapped_column(STRING_LIST_TYPE, nullable=False)
    correct_form: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    context_hint: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON_TYPE)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConfigProfile(Base):
    __tablename__ = "config_profiles"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    packaging_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PackagingAsset(Base):
    __tablename__ = "packaging_assets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    watermark_preprocessed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())


class CreatorCard(Base):
    __tablename__ = "creator_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    positioning: Mapped[str | None] = mapped_column(Text)
    content_domains: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list, server_default="[]")
    audience: Mapped[str | None] = mapped_column(Text)
    default_platforms: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list, server_default="[]")
    natural_language_profile: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    assets: Mapped[list[CreatorAsset]] = relationship(
        "CreatorAsset",
        back_populates="creator_card",
        cascade="all, delete-orphan",
    )
    preferences: Mapped[list[CreatorPreference]] = relationship(
        "CreatorPreference",
        back_populates="creator_card",
        cascade="all, delete-orphan",
    )
    task_strategies: Mapped[list[CreatorTaskStrategy]] = relationship(
        "CreatorTaskStrategy",
        back_populates="creator_card",
        cascade="all, delete-orphan",
    )
    visual_plans: Mapped[list[CreatorVisualPlan]] = relationship(
        "CreatorVisualPlan",
        back_populates="creator_card",
        cascade="all, delete-orphan",
    )
    publication_profile: Mapped[CreatorPublicationProfile | None] = relationship(
        "CreatorPublicationProfile",
        back_populates="creator_card",
        cascade="all, delete-orphan",
        uselist=False,
    )
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="creator_card")


class CreatorAsset(Base):
    __tablename__ = "creator_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    creator_card_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    creator_card: Mapped[CreatorCard] = relationship("CreatorCard", back_populates="assets")


class CreatorPreference(Base):
    __tablename__ = "creator_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    creator_card_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="CASCADE"))
    preference_type: Mapped[str] = mapped_column(Text, nullable=False)
    natural_language_rule: Mapped[str] = mapped_column(Text, nullable=False)
    structured_payload: Mapped[dict | None] = mapped_column(JSON_TYPE)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual", server_default="manual")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    creator_card: Mapped[CreatorCard] = relationship("CreatorCard", back_populates="preferences")


class CreatorTaskStrategy(Base):
    __tablename__ = "creator_task_strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    creator_card_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_type: Mapped[str] = mapped_column(Text, nullable=False, default="generic", server_default="generic")
    summary: Mapped[str | None] = mapped_column(Text)
    strategy_payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    creator_card: Mapped[CreatorCard] = relationship("CreatorCard", back_populates="task_strategies")
    versions: Mapped[list[TaskStrategyVersion]] = relationship(
        "TaskStrategyVersion",
        back_populates="strategy",
        cascade="all, delete-orphan",
        order_by="TaskStrategyVersion.version",
    )


class TaskStrategyVersion(Base):
    __tablename__ = "task_strategy_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_task_strategies.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False, default="generate", server_default="generate")
    prompt: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    strategy: Mapped[CreatorTaskStrategy] = relationship("CreatorTaskStrategy", back_populates="versions")


class CreatorVisualPlan(Base):
    __tablename__ = "creator_visual_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    creator_card_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    visual_payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    creator_card: Mapped[CreatorCard] = relationship("CreatorCard", back_populates="visual_plans")
    versions: Mapped[list[VisualPlanVersion]] = relationship(
        "VisualPlanVersion",
        back_populates="visual_plan",
        cascade="all, delete-orphan",
        order_by="VisualPlanVersion.version",
    )


class VisualPlanVersion(Base):
    __tablename__ = "visual_plan_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    visual_plan_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_visual_plans.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False, default="generate", server_default="generate")
    prompt: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    visual_plan: Mapped[CreatorVisualPlan] = relationship("CreatorVisualPlan", back_populates="versions")


class CreatorPublicationProfile(Base):
    __tablename__ = "creator_publication_profiles"
    __table_args__ = (UniqueConstraint("creator_card_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    creator_card_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    publication_payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    creator_card: Mapped[CreatorCard] = relationship("CreatorCard", back_populates="publication_profile")
    bindings: Mapped[list[CreatorPlatformBinding]] = relationship(
        "CreatorPlatformBinding",
        back_populates="publication_profile",
        cascade="all, delete-orphan",
    )
    versions: Mapped[list[PublicationProfileVersion]] = relationship(
        "PublicationProfileVersion",
        back_populates="publication_profile",
        cascade="all, delete-orphan",
        order_by="PublicationProfileVersion.version",
    )


class CreatorPlatformBinding(Base):
    __tablename__ = "creator_platform_bindings"
    __table_args__ = (UniqueConstraint("publication_profile_id", "platform"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    publication_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_publication_profiles.id", ondelete="CASCADE"),
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(Text)
    binding_payload_json: Mapped[dict | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    publication_profile: Mapped[CreatorPublicationProfile] = relationship(
        "CreatorPublicationProfile",
        back_populates="bindings",
    )


class PublicationProfileVersion(Base):
    __tablename__ = "publication_profile_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    publication_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_publication_profiles.id", ondelete="CASCADE"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False, default="refine", server_default="refine")
    prompt: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    publication_profile: Mapped[CreatorPublicationProfile] = relationship(
        "CreatorPublicationProfile",
        back_populates="versions",
    )


class JobAgentPlan(Base):
    __tablename__ = "job_agent_plans"
    __table_args__ = (UniqueConstraint("job_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("jobs.id", ondelete="CASCADE"))
    creator_card_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("creator_cards.id", ondelete="SET NULL"))
    task_strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_task_strategies.id", ondelete="SET NULL"),
    )
    visual_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_visual_plans.id", ondelete="SET NULL"),
    )
    publication_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("creator_publication_profiles.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    plan_payload_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now(), onupdate=func.now())

    job: Mapped[Job] = relationship("Job", back_populates="agent_plan")
