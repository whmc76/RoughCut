from __future__ import annotations

from roughcut.creative.avatar import build_avatar_commentary_plan
from roughcut.creative.avatar import refine_avatar_commentary_segments_for_media_duration


def test_build_avatar_commentary_plan_prefers_full_track_passthrough(monkeypatch):
    import roughcut.creative.avatar as avatar_mod

    class DummyProvider:
        def build_render_request(self, *, job_id: str, plan: dict[str, object]):
            return {"job_id": job_id, "segments": list(plan.get("segments") or [])}

    monkeypatch.setattr(avatar_mod, "get_avatar_provider", lambda: DummyProvider())

    subtitle_items = [
        {"start_time": 0.0, "end_time": 3.2, "text_final": "第一段解说"},
        {"start_time": 3.3, "end_time": 6.4, "text_final": "继续补充说明"},
        {"start_time": 9.0, "end_time": 13.6, "text_final": "第二段话题切换"},
    ]

    plan = build_avatar_commentary_plan(
        job_id="job-1",
        source_name="demo.mp4",
        subtitle_items=subtitle_items,
        content_profile={},
    )

    assert plan["mode"] == "full_track_audio_passthrough"
    assert plan["segments"] == []
    assert plan["render_request"]["segments"] == plan["segments"]
    assert any("等长" in item for item in plan["design_rules"])


def test_build_avatar_commentary_plan_keeps_source_identity_constraints(monkeypatch):
    import roughcut.creative.avatar as avatar_mod

    class DummyProvider:
        def build_render_request(self, *, job_id: str, plan: dict[str, object]):
            return {"job_id": job_id, "segments": list(plan.get("segments") or [])}

    monkeypatch.setattr(avatar_mod, "get_avatar_provider", lambda: DummyProvider())

    plan = build_avatar_commentary_plan(
        job_id="job-2",
        source_name="watch_merge_olight.mp4",
        subtitle_items=[],
        content_profile={
            "source_context": {
                "video_description": "任务说明依据文件名：傲雷司令官2代Ultra开箱，并与EDC23做对比。",
                "resolved_feedback": {
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2代Ultra",
                    "subject_type": "EDC手电",
                    "video_theme": "傲雷司令官2代Ultra开箱与EDC23对比",
                },
            }
        },
    )

    assert plan["content_identity"]["subject_brand"] == "傲雷"
    assert plan["content_identity"]["subject_model"] == "司令官2代Ultra"
    assert any("强约束" in item for item in plan["design_rules"])


def test_build_avatar_commentary_plan_still_defaults_full_track_with_reset_timestamps(monkeypatch):
    import roughcut.creative.avatar as avatar_mod

    class DummyProvider:
        def build_render_request(self, *, job_id: str, plan: dict[str, object]):
            return {"job_id": job_id, "segments": list(plan.get("segments") or [])}

    monkeypatch.setattr(avatar_mod, "get_avatar_provider", lambda: DummyProvider())

    subtitle_items = [
        {"start_time": 0.5, "end_time": 4.0, "text_final": "第一段介绍"},
        {"start_time": 4.2, "end_time": 8.1, "text_final": "继续补充"},
        {"start_time": 0.3, "end_time": 3.6, "text_final": "第二段素材重新从零开始"},
        {"start_time": 3.8, "end_time": 7.2, "text_final": "继续第二段说明"},
    ]

    plan = build_avatar_commentary_plan(
        job_id="job-3",
        source_name="watch_merge_demo.mp4",
        subtitle_items=subtitle_items,
        content_profile={},
    )

    assert plan["mode"] == "full_track_audio_passthrough"
    assert plan["segments"] == []


def test_build_avatar_commentary_plan_skips_subsecond_segments(monkeypatch):
    import roughcut.creative.avatar as avatar_mod

    class DummyProvider:
        def build_render_request(self, *, job_id: str, plan: dict[str, object]):
            return {"job_id": job_id, "segments": list(plan.get("segments") or [])}

    monkeypatch.setattr(avatar_mod, "get_avatar_provider", lambda: DummyProvider())

    plan = build_avatar_commentary_plan(
        job_id="job-4",
        source_name="demo.mp4",
        subtitle_items=[
            {"start_time": 1.0, "end_time": 1.64, "text_final": "太短了"},
            {"start_time": 5.0, "end_time": 5.8, "text_final": "还是太短"},
        ],
        content_profile={},
    )

    assert plan["mode"] == "full_track_audio_passthrough"
    assert plan["segments"] == []


def test_refine_avatar_commentary_segments_for_media_duration_rebuilds_within_media_bounds():
    subtitle_items = [
        {"start_time": 10.0, "end_time": 13.0, "text_final": "开场说明"},
        {"start_time": 40.0, "end_time": 44.0, "text_final": "中段说明"},
        {"start_time": 70.0, "end_time": 75.0, "text_final": "超时长说明"},
    ]
    original_segments = [
        {
            "segment_id": "avatar_seg_001",
            "script": "超时长说明",
            "start_time": 70.0,
            "end_time": 75.0,
            "duration_sec": 5.0,
            "purpose": "commentary",
        }
    ]

    refined = refine_avatar_commentary_segments_for_media_duration(
        original_segments,
        subtitle_items,
        media_duration_sec=50.0,
    )

    assert refined
    assert all(float(item["end_time"]) <= 50.0 for item in refined)
    assert any("开场说明" in str(item.get("script") or "") or "中段说明" in str(item.get("script") or "") for item in refined)
