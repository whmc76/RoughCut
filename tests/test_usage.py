from __future__ import annotations

from pathlib import Path
import uuid
from datetime import datetime, timezone

import pytest

from types import SimpleNamespace

from roughcut.db.models import JobStep
from roughcut.llm_cache import load_cached_entry, save_cached_json
from roughcut.review.platform_copy import build_packaging_prompt_brief, build_transcript_for_packaging
from roughcut.usage import build_job_token_report, build_jobs_usage_summary, build_jobs_usage_trend


def test_build_job_token_report_aggregates_step_metadata():
    job_id = uuid.uuid4()
    steps = [
        JobStep(
            job_id=job_id,
            step_name="content_profile",
            metadata_={
                "cache": {
                    "content_profile": {
                        "namespace": "content_profile.infer",
                        "key": "cache-key-1",
                        "hit": True,
                        "usage_baseline": {
                            "calls": 2,
                            "prompt_tokens": 1200,
                            "completion_tokens": 300,
                            "total_tokens": 1500,
                        },
                    }
                },
                "llm_usage": {
                    "calls": 2,
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "by_operation": {
                        "content_profile.visual_transcript_fuse": {
                            "calls": 1,
                            "prompt_tokens": 700,
                            "completion_tokens": 160,
                            "total_tokens": 860,
                        },
                        "content_profile.text_refine": {
                            "calls": 1,
                            "prompt_tokens": 500,
                            "completion_tokens": 140,
                            "total_tokens": 640,
                        },
                    },
                    "by_model": {
                        "MiniMax-M2.7-highspeed": {
                            "provider": "minimax",
                            "kind": "reasoning",
                            "calls": 2,
                            "prompt_tokens": 1200,
                            "completion_tokens": 300,
                            "total_tokens": 1500,
                        }
                    },
                }
            },
        ),
        JobStep(
            job_id=job_id,
            step_name="platform_package",
            metadata_={
                "llm_usage": {
                    "calls": 1,
                    "prompt_tokens": 900,
                    "completion_tokens": 220,
                    "total_tokens": 1120,
                    "by_operation": {
                        "platform_package.generate_packaging": {
                            "calls": 1,
                            "prompt_tokens": 900,
                            "completion_tokens": 220,
                            "total_tokens": 1120,
                        }
                    },
                    "by_model": {
                        "MiniMax-M2.7-highspeed": {
                            "provider": "minimax",
                            "kind": "reasoning",
                            "calls": 1,
                            "prompt_tokens": 900,
                            "completion_tokens": 220,
                            "total_tokens": 1120,
                        }
                    },
                }
            },
        ),
    ]

    report = build_job_token_report(steps, step_labels={"content_profile": "内容摘要", "platform_package": "平台文案"})

    assert report["has_telemetry"] is True
    assert report["total_calls"] == 3
    assert report["total_prompt_tokens"] == 2100
    assert report["total_completion_tokens"] == 520
    assert report["total_tokens"] == 2620
    assert report["cache"]["hits"] == 1
    assert report["cache"]["avoided_calls"] == 1
    assert report["cache"]["saved_total_tokens"] == 1500
    assert report["cache"]["hits_with_usage_baseline"] == 1
    assert report["steps"][0]["step_name"] == "content_profile"
    assert report["steps"][0]["cache_entries"][0]["name"] == "content_profile"
    assert report["steps"][0]["cache_entries"][0]["usage_baseline"]["total_tokens"] == 1500
    assert report["steps"][0]["operations"][0]["operation"] == "content_profile.visual_transcript_fuse"
    assert report["models"][0]["model"] == "MiniMax-M2.7-highspeed"
    assert report["models"][0]["total_tokens"] == 2620


def test_llm_cache_persists_usage_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.llm_cache as llm_cache_mod

    monkeypatch.setattr(
        llm_cache_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(tmp_path)),
    )

    save_cached_json(
        "content_profile.infer",
        "cache-key-1",
        fingerprint={"source_name": "demo.mp4"},
        result={"summary": "demo"},
        usage_baseline={"calls": 2, "prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300},
    )

    entry = load_cached_entry("content_profile.infer", "cache-key-1")

    assert entry is not None
    assert entry["result"]["summary"] == "demo"
    assert entry["usage_baseline"]["total_tokens"] == 1300


def test_build_jobs_usage_summary_rolls_up_cache_and_steps():
    job_id = uuid.uuid4()
    jobs = [
        SimpleNamespace(
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="content_profile",
                    metadata_={
                        "cache": {
                            "content_profile": {
                                "namespace": "content_profile.infer",
                                "key": "k1",
                                "hit": True,
                                "usage_baseline": {
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                },
                            }
                        },
                        "llm_usage": {
                            "calls": 2,
                            "prompt_tokens": 1000,
                            "completion_tokens": 300,
                            "total_tokens": 1300,
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                }
                            },
                        },
                    },
                )
            ]
        ),
        SimpleNamespace(
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    metadata_={
                        "cache": {"platform_packaging": {"namespace": "platform_package.generate", "key": "k2", "hit": False}},
                        "llm_usage": {
                            "calls": 1,
                            "prompt_tokens": 900,
                            "completion_tokens": 200,
                            "total_tokens": 1100,
                            "by_model": {
                                "gpt-4.1-mini": {
                                    "provider": "openai",
                                    "kind": "reasoning",
                                    "calls": 1,
                                    "prompt_tokens": 900,
                                    "completion_tokens": 200,
                                    "total_tokens": 1100,
                                }
                            },
                        },
                    },
                )
            ]
        ),
    ]

    summary = build_jobs_usage_summary(jobs, step_labels={"content_profile": "内容摘要", "platform_package": "平台文案"})

    assert summary["job_count"] == 2
    assert summary["jobs_with_telemetry"] == 2
    assert summary["total_tokens"] == 2400
    assert summary["cache"]["hits"] == 1
    assert summary["cache"]["misses"] == 1
    assert summary["cache"]["hit_rate"] == 0.5
    assert summary["cache"]["saved_total_tokens"] == 1300
    assert summary["top_steps"][0]["step_name"] == "content_profile"
    assert summary["top_models"][0]["model"] == "MiniMax-M2.7-highspeed"
    assert summary["top_providers"][0]["provider"] == "minimax"


def test_build_jobs_usage_trend_groups_recent_days():
    job_id = uuid.uuid4()
    jobs = [
        SimpleNamespace(
            updated_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="content_profile",
                    metadata_={
                        "cache": {
                            "content_profile": {
                                "namespace": "content_profile.infer",
                                "key": "k1",
                                "hit": True,
                                "usage_baseline": {
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                },
                            }
                        },
                        "llm_usage": {"calls": 2, "prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300},
                    },
                )
            ],
        ),
        SimpleNamespace(
            updated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    metadata_={
                        "cache": {"platform_packaging": {"namespace": "platform_package.generate", "key": "k2", "hit": False}},
                        "llm_usage": {"calls": 1, "prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
                    },
                )
            ],
        ),
    ]

    trend = build_jobs_usage_trend(
        jobs,
        days=3,
        step_labels={"content_profile": "内容摘要", "platform_package": "平台文案"},
        now=datetime(2026, 3, 22, 15, 0, tzinfo=timezone.utc),
    )

    assert trend["days"] == 3
    assert [point["date"] for point in trend["points"]] == ["2026-03-20", "2026-03-21", "2026-03-22"]
    assert trend["points"][0]["total_tokens"] == 1300
    assert trend["points"][0]["cache"]["hits"] == 1
    assert trend["points"][0]["cache"]["saved_total_tokens"] == 1300
    assert trend["points"][1]["total_tokens"] == 0
    assert trend["points"][2]["top_step"]["step_name"] == "platform_package"


def test_build_jobs_usage_trend_filters_by_step_name():
    job_id = uuid.uuid4()
    jobs = [
        SimpleNamespace(
            updated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="content_profile",
                    metadata_={"llm_usage": {"calls": 2, "prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300}},
                ),
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    metadata_={"llm_usage": {"calls": 1, "prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000}},
                ),
            ],
        ),
    ]

    trend = build_jobs_usage_trend(
        jobs,
        days=1,
        step_name="platform_package",
        step_labels={"content_profile": "内容摘要", "platform_package": "平台文案"},
        now=datetime(2026, 3, 22, 15, 0, tzinfo=timezone.utc),
    )

    assert trend["points"][0]["total_tokens"] == 1000
    assert trend["points"][0]["total_calls"] == 1
    assert trend["points"][0]["top_step"]["step_name"] == "platform_package"


def test_build_jobs_usage_trend_groups_by_model_and_provider_without_fake_cache():
    job_id = uuid.uuid4()
    jobs = [
        SimpleNamespace(
            updated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            steps=[
                JobStep(
                    job_id=job_id,
                    step_name="content_profile",
                    metadata_={
                        "cache": {"content_profile": {"namespace": "content_profile.infer", "key": "k1", "hit": True}},
                        "llm_usage": {
                            "calls": 2,
                            "prompt_tokens": 1000,
                            "completion_tokens": 300,
                            "total_tokens": 1300,
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                }
                            },
                        },
                    },
                ),
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    metadata_={
                        "llm_usage": {
                            "calls": 1,
                            "prompt_tokens": 800,
                            "completion_tokens": 200,
                            "total_tokens": 1000,
                            "by_model": {
                                "gpt-4.1-mini": {
                                    "provider": "openai",
                                    "kind": "reasoning",
                                    "calls": 1,
                                    "prompt_tokens": 800,
                                    "completion_tokens": 200,
                                    "total_tokens": 1000,
                                }
                            },
                        },
                    },
                ),
            ],
        ),
    ]

    model_trend = build_jobs_usage_trend(
        jobs,
        days=1,
        focus_type="model",
        focus_name="MiniMax-M2.7-highspeed",
        now=datetime(2026, 3, 22, 15, 0, tzinfo=timezone.utc),
    )
    provider_trend = build_jobs_usage_trend(
        jobs,
        days=1,
        focus_type="provider",
        focus_name="openai",
        now=datetime(2026, 3, 22, 15, 0, tzinfo=timezone.utc),
    )

    assert model_trend["focus_type"] == "model"
    assert model_trend["focus_name"] == "MiniMax-M2.7-highspeed"
    assert model_trend["points"][0]["total_tokens"] == 1300
    assert model_trend["points"][0]["cache"]["total_entries"] == 0
    assert model_trend["points"][0]["top_entry"]["dimension"] == "model"
    assert provider_trend["points"][0]["total_tokens"] == 1000
    assert provider_trend["points"][0]["top_entry"]["name"] == "openai"


def test_build_transcript_for_packaging_samples_head_middle_tail_when_too_long():
    subtitle_items = [
        {"start_time": float(index), "end_time": float(index) + 0.8, "text_final": f"line-{index:02d}-" + ("A" * 40)}
        for index in range(18)
    ]

    transcript = build_transcript_for_packaging(subtitle_items, max_chars=260)

    assert "line-00" in transcript
    assert any(f"line-{index:02d}" in transcript for index in range(6, 12))
    assert "line-17" in transcript
    assert len(transcript) <= 260


def test_build_packaging_prompt_brief_keeps_only_compact_fields():
    brief = build_packaging_prompt_brief(
        source_name="demo.mp4",
        content_profile={
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代Pro UV版",
            "subject_type": "EDC手电",
            "subject_domain": "edc",
            "video_theme": "上手开箱",
            "summary": "这期重点看真实上手体验。",
            "hook_line": "这次升级有点猛",
            "engagement_question": "你更看重泛光还是紫外？",
            "cover_title": {"top": "Loop露普", "main": "SK05二代", "bottom": "上手开箱"},
            "evidence": [{"title": "should not be copied"}],
            "automation_review": {"score": 0.95},
        },
        subtitle_items=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "先看外观。"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "再看紫外效果。"},
        ],
    )

    assert brief["source_name"] == "demo.mp4"
    assert brief["subject_brand"] == "Loop露普"
    assert brief["subject_domain"] == "edc"
    assert "evidence" not in brief
    assert "automation_review" not in brief
    assert "先看外观" in brief["transcript_excerpt"]


@pytest.mark.asyncio
async def test_infer_content_profile_skips_text_refine_when_visual_fusion_is_specific(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    monkeypatch.setattr(content_profile_module, "_extract_reference_frames", lambda *args, **kwargs: [Path("frame_01.jpg")])
    async def fake_infer_visual_profile_hints(frame_paths):
        return {
            "subject_type": "EDC手电",
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代Pro UV版",
            "visible_text": "Loop SK05",
        }

    monkeypatch.setattr(content_profile_module, "_infer_visual_profile_hints", fake_infer_visual_profile_hints)

    async def fake_complete_with_images(*args, **kwargs):
        return (
            '{"subject_brand":"Loop露普","subject_model":"SK05二代Pro UV版","subject_type":"EDC手电",'
            '"video_theme":"EDC手电开箱与紫外实测","preset_name":"unboxing_upgrade",'
            '"hook_line":"这次升级看紫外实测","visible_text":"Loop SK05",'
            '"engagement_question":"这类手电你更看重泛光还是紫外？","search_queries":["Loop SK05 UV"]}'
        )

    monkeypatch.setattr(content_profile_module, "complete_with_images", fake_complete_with_images)

    def fail_provider():
        raise AssertionError("text refine should not be called")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", fail_provider)

    result = await content_profile_module.infer_content_profile(
        source_path=Path("demo.mp4"),
        source_name="demo.mp4",
        subtitle_items=[{"text_final": "这次重点看紫外效果和泛光。", "start_time": 0.0, "end_time": 1.0}],
        channel_profile=None,
        include_research=False,
    )

    assert result["subject_brand"] == "Loop露普"
    assert result["video_theme"] == "EDC手电开箱与紫外实测"
