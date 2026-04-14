from __future__ import annotations

import pytest

from roughcut.creative.director import _build_heuristic_director_plan, build_ai_director_plan


def test_heuristic_director_plan_uses_creative_preferences():
    plan = _build_heuristic_director_plan(
        source_name="demo.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 1.5, "text_final": "先说开头。"},
            {"start_time": 2.0, "end_time": 4.0, "text_final": "中间讲细节。"},
            {"start_time": 8.0, "end_time": 10.0, "text_final": "最后做收口。"},
        ],
        content_profile={
            "subject_type": "EDC手电",
            "summary": "这期重点讲版本差异和怎么选。",
            "creative_preferences": [
                {"tag": "comparison_focus", "count": 3},
                {"tag": "fast_paced", "count": 2},
                {"tag": "closeup_focus", "count": 2},
            ],
        },
    )

    assert "差异" in plan["opening_hook"] or "怎么选" in plan["opening_hook"]
    assert "差异" in plan["bridge_line"] or "取舍" in plan["bridge_line"]
    assert "细节" in plan["science_boost"] or "近景" in plan["science_boost"]
    assert any("结论" in item or "重点" in item for item in plan["rewrite_strategy"])


@pytest.mark.asyncio
async def test_build_ai_director_plan_treats_source_identity_as_hard_constraint(monkeypatch):
    import roughcut.creative.director as director_mod

    captured: dict[str, str] = {}

    class DummyResponse:
        def as_json(self):
            return {}

    class DummyProvider:
        async def complete(self, messages, **kwargs):
            captured["prompt"] = messages[-1].content
            return DummyResponse()

    class DummyVoiceProvider:
        def build_dubbing_request(self, *, job_id, segments, metadata):
            return {"job_id": job_id, "segments": segments, "metadata": metadata}

    monkeypatch.setattr(director_mod, "get_reasoning_provider", lambda: DummyProvider())
    monkeypatch.setattr(director_mod, "get_voice_provider", lambda: DummyVoiceProvider())

    plan = await build_ai_director_plan(
        job_id="job-1",
        source_name="watch_merge_reate_exo.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "今天继续讲这个产品。"},
            {"start_time": 2.5, "end_time": 5.0, "text_final": "后面再带一下新品预告。"},
        ],
        content_profile={
            "subject_type": "键盘",
            "summary": "泛化摘要",
            "source_context": {
                "video_description": "任务说明依据文件名：继续讲解 REATE EXO 重力刀和 FAS 新款 EDC 整备卷轴的新品预告。",
                "resolved_feedback": {
                    "subject_brand": "REATE",
                    "subject_model": "EXO",
                    "subject_type": "重力刀",
                    "video_theme": "REATE EXO重力刀讲解与FAS新品预告",
                },
            },
        },
    )

    assert "强约束" in captured["prompt"]
    assert "REATE" in captured["prompt"]
    assert "EXO" in captured["prompt"]
    assert "重力刀" in captured["prompt"]
    assert "重力刀" in plan["opening_hook"]
