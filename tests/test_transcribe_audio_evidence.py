from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, Job, JobStep
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER


@pytest.mark.asyncio
async def test_transcribe_audio_persists_transcript_evidence_artifact_when_enabled(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.speech.transcribe as transcribe_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    async with factory() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
        step = JobStep(job_id=job_id, step_name="transcribe", status="running")
        session.add(job)
        session.add(step)
        await session.commit()

        monkeypatch.setattr(
            transcribe_mod,
            "get_settings",
            lambda: SimpleNamespace(
                transcription_provider="openai",
                transcription_model="gpt-4o-transcribe",
                asr_evidence_enabled=True,
            ),
        )

        async def fake_execute_transcription_plan(**kwargs):
            return (
                TranscriptResult(
                    segments=[
                        TranscriptSegment(
                            index=0,
                            start=0.0,
                            end=1.0,
                            text="傲雷 司令官二",
                            raw_text="奥雷 司令官二",
                            provider="qwen3_asr",
                            model="qwen3-asr-1.7b",
                            raw_payload={"text": "奥雷 司令官二"},
                            words=[
                                WordTiming(
                                    word="奥雷",
                                    start=0.0,
                                    end=0.3,
                                    raw_payload={"word": "奥雷"},
                                )
                            ],
                        )
                    ],
                    language="zh-CN",
                    duration=1.0,
                    provider="qwen3_asr",
                    model="qwen3-asr-1.7b",
                    raw_payload={"segments": [{"text": "奥雷 司令官二"}]},
                    context="热词：傲雷,司令官2 Ultra",
                    hotword="傲雷,司令官2 Ultra",
                ),
                "qwen3_asr",
                "qwen3-asr-1.7b",
                [{"provider": "openai", "model": "gpt-4o-transcribe", "error": "missing key"}],
            )

        monkeypatch.setattr(transcribe_mod, "execute_transcription_plan", fake_execute_transcription_plan)

        await transcribe_mod.transcribe_audio(
            job_id,
            step,
            audio_path,
            "zh-CN",
            session,
            prompt="热词：傲雷,司令官2 Ultra",
            glossary_terms=[],
            review_memory=None,
        )
        await session.commit()

    async with factory() as session:
        artifact = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript_evidence")
            )
        ).scalar_one()
        transcript_fact_layer = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER)
            )
        ).scalar_one()

        assert artifact.data_json["provider"] == "qwen3_asr"
        assert artifact.data_json["model"] == "qwen3-asr-1.7b"
        assert artifact.data_json["prompt"] == "热词：傲雷,司令官2 Ultra"
        assert artifact.data_json["attempts"][0]["provider"] == "openai"
        assert artifact.data_json["alignment"]["segments_total"] == 1
        assert artifact.data_json["raw_payload"] == {"segments": [{"text": "奥雷 司令官二"}]}
        assert artifact.data_json["raw_segments"][0]["raw_text"] == "奥雷 司令官二"
        assert artifact.data_json["raw_segments"][0]["words"][0]["raw_payload"] == {"word": "奥雷"}
        assert transcript_fact_layer.data_json["layer"] == "transcript_fact"
        assert transcript_fact_layer.data_json["segments"][0]["text"] == "傲雷 司令官二"
        assert transcript_fact_layer.data_json["segments"][0]["words"][0]["word"] == "奥雷"


@pytest.mark.asyncio
async def test_transcribe_audio_sanitizes_non_json_evidence_payloads(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.speech.transcribe as transcribe_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    class FakeTranscriptionOptions:
        def __init__(self) -> None:
            self.beam_size = 6
            self.best_of = 6

    async with factory() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
        step = JobStep(job_id=job_id, step_name="transcribe", status="running")
        session.add(job)
        session.add(step)
        await session.commit()

        monkeypatch.setattr(
            transcribe_mod,
            "get_settings",
            lambda: SimpleNamespace(
                transcription_provider="faster_whisper",
                transcription_model="large-v3",
                asr_evidence_enabled=True,
            ),
        )

        async def fake_execute_transcription_plan(**kwargs):
            return (
                TranscriptResult(
                    segments=[
                        TranscriptSegment(
                            index=0,
                            start=np.float64(0.0),
                            end=np.float64(1.0),
                            text="测试文本",
                            raw_payload={
                                "options": FakeTranscriptionOptions(),
                            },
                            words=[
                                WordTiming(
                                    word="测试",
                                    start=np.float64(0.0),
                                    end=np.float64(0.4),
                                    raw_payload={"timing": np.float64(0.4)},
                                )
                            ],
                        )
                    ],
                    language="zh-CN",
                    duration=np.float64(1.0),
                    provider="faster_whisper",
                    model="large-v3",
                    raw_payload={
                        "transcribe_kwargs": {
                            "options": FakeTranscriptionOptions(),
                            "temperature": np.float64(0.0),
                        }
                    },
                ),
                "faster_whisper",
                "large-v3",
                [],
            )

        monkeypatch.setattr(transcribe_mod, "execute_transcription_plan", fake_execute_transcription_plan)

        await transcribe_mod.transcribe_audio(
            job_id,
            step,
            audio_path,
            "zh-CN",
            session,
            prompt="测试提示",
            glossary_terms=[],
            review_memory=None,
        )
        await session.commit()

    async with factory() as session:
        transcript = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript")
            )
        ).scalar_one()
        transcript_evidence = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript_evidence")
            )
        ).scalar_one()
        transcript_fact_layer = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER)
            )
        ).scalar_one()

        assert transcript.data_json["duration"] == 1.0
        assert transcript_evidence.data_json["duration"] == 1.0
        assert transcript_evidence.data_json["raw_payload"]["transcribe_kwargs"]["options"] == {
            "beam_size": 6,
            "best_of": 6,
        }
        assert transcript_evidence.data_json["raw_payload"]["transcribe_kwargs"]["temperature"] == 0.0
        assert transcript_evidence.data_json["segments"][0]["raw_payload"]["options"] == {
            "beam_size": 6,
            "best_of": 6,
        }
        assert transcript_evidence.data_json["segments"][0]["words"][0]["raw_payload"]["timing"] == 0.4
        assert transcript_fact_layer.data_json["segment_count"] == 1
        assert transcript_fact_layer.data_json["segments"][0]["words"][0]["raw_payload"]["timing"] == 0.4


@pytest.mark.asyncio
async def test_transcribe_audio_filters_tail_cta_noise_from_persisted_segments(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.speech.transcribe as transcribe_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    async with factory() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
        step = JobStep(job_id=job_id, step_name="transcribe", status="running")
        session.add(job)
        session.add(step)
        await session.commit()

        monkeypatch.setattr(
            transcribe_mod,
            "get_settings",
            lambda: SimpleNamespace(
                transcription_provider="qwen3_asr",
                transcription_model="qwen3-asr-1.7b",
                asr_evidence_enabled=True,
            ),
        )

        async def fake_execute_transcription_plan(**kwargs):
            intro_segment = TranscriptSegment(
                index=0,
                start=892.0,
                end=896.5,
                text="然后前置的这个大拇指推很轻松。",
                raw_text="然后前置的这个大拇指推很轻松。",
            )
            noise_segment = TranscriptSegment(
                index=1,
                start=876.9,
                end=877.0,
                text="请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
                raw_text="请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
            )
            return (
                TranscriptResult(
                    segments=[intro_segment, noise_segment],
                    language="zh-CN",
                    duration=900.0,
                    provider="qwen3_asr",
                    model="qwen3-asr-1.7b",
                    raw_payload={"segments": [{"text": intro_segment.text}, {"text": noise_segment.text}]},
                    raw_segments=[intro_segment, noise_segment],
                ),
                "qwen3_asr",
                "qwen3-asr-1.7b",
                [],
            )

        monkeypatch.setattr(transcribe_mod, "execute_transcription_plan", fake_execute_transcription_plan)

        await transcribe_mod.transcribe_audio(
            job_id,
            step,
            audio_path,
            "zh-CN",
            session,
            prompt="测试尾部幻觉过滤",
            glossary_terms=[],
            review_memory=None,
        )
        await session.commit()

    async with factory() as session:
        transcript_evidence = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript_evidence")
            )
        ).scalar_one()
        transcript_fact_layer = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER)
            )
        ).scalar_one()

        assert [segment["text"] for segment in transcript_evidence.data_json["segments"]] == ["然后前置的这个大拇指推很轻松。"]
        assert len(transcript_evidence.data_json["raw_segments"]) == 2
        assert transcript_evidence.data_json["raw_segments"][-1]["text"] == "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"
        assert transcript_evidence.data_json["raw_payload"]["_roughcut_filtering"]["dropped_tail_cta_segments"][0]["reason"] == "tail_cta_noise"
        assert [segment["text"] for segment in transcript_fact_layer.data_json["segments"]] == ["然后前置的这个大拇指推很轻松。"]
