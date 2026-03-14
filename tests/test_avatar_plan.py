from __future__ import annotations

from roughcut.creative.avatar import build_avatar_commentary_plan


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
