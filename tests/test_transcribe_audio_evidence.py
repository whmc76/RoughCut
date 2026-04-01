from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, Job, JobStep
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming


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

        assert artifact.data_json["provider"] == "qwen3_asr"
        assert artifact.data_json["model"] == "qwen3-asr-1.7b"
        assert artifact.data_json["prompt"] == "热词：傲雷,司令官2 Ultra"
        assert artifact.data_json["attempts"][0]["provider"] == "openai"
        assert artifact.data_json["raw_payload"] == {"segments": [{"text": "奥雷 司令官二"}]}
        assert artifact.data_json["raw_segments"][0]["raw_text"] == "奥雷 司令官二"
        assert artifact.data_json["raw_segments"][0]["words"][0]["raw_payload"] == {"word": "奥雷"}
