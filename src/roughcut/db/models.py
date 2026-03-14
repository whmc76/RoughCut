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
    channel_profile: Mapped[str | None] = mapped_column(Text)
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
    channel_profile: Mapped[str | None] = mapped_column(Text)
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


class WatchRoot(Base):
    __tablename__ = "watch_roots"
    __table_args__ = (UniqueConstraint("path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    channel_profile: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scan_mode: Mapped[str] = mapped_column(Text, nullable=False, default="fast", server_default="fast")
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


class ChannelProfile(Base):
    __tablename__ = "channel_profiles"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    config_json: Mapped[dict] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
