import asyncio

from roughcut.edit.local_audio_cues import (
    normalize_local_music_plan,
    plan_local_music_entry,
    score_local_music_entry_candidates,
)
from roughcut.edit.packaging_timeline import (
    packaging_timeline_local_audio_cues,
    packaging_timeline_music_plan,
)


def test_score_local_music_entry_candidates_prefers_natural_sentence_endings() -> None:
    rankings = score_local_music_entry_candidates(
        [
            {"start_time": 0.0, "end_time": 2.2, "text_final": "先开场铺垫一下"},
            {"start_time": 2.5, "end_time": 5.4, "text_final": "这里先把核心结论讲完。"},
            {"start_time": 6.0, "end_time": 8.6, "text_final": "然后继续展开细节"},
        ],
        content_profile={"content_kind": "commentary"},
    )

    assert rankings
    assert rankings[0]["enter_sec"] == 5.4
    assert "句子在这里收束" in rankings[0]["reasons"]


def test_plan_local_music_entry_adds_shared_audio_cue_contract() -> None:
    plan = asyncio.run(
        plan_local_music_entry(
            music_plan={"asset_id": "music-a", "path": "bgm.mp3"},
            subtitle_items=[
                {"start_time": 0.0, "end_time": 2.4, "text_final": "开场先铺一下问题"},
                {"start_time": 2.8, "end_time": 5.6, "text_final": "这里直接把重点说完。"},
            ],
            content_profile={"content_kind": "tutorial"},
            timeline_analysis={"hook_end_sec": 2.0},
        )
    )

    assert plan is not None
    assert plan["enter_sec"] == 5.6
    assert plan["audio_cues"][0]["kind"] == "bgm_entry"
    assert plan["audio_cues"][0]["time_sec"] == 5.6


def test_packaging_timeline_local_audio_cues_reads_music_and_sfx() -> None:
    payload = {
        "packaging_timeline": {
            "packaging": {
                "music": normalize_local_music_plan(
                    {
                        "asset_id": "music-a",
                        "path": "bgm.mp3",
                        "enter_sec": 4.2,
                        "entry_reason": "测试进入点",
                        "timing_summary": {"review_recommended": False},
                    }
                )
            },
            "editing_accents": {
                "sound_effects": [
                    {"start_time": 1.1, "duration_sec": 0.08, "frequency": 960, "volume": 0.05}
                ]
            },
        }
    }

    music_plan = packaging_timeline_music_plan(payload)
    cues = packaging_timeline_local_audio_cues(payload)

    assert music_plan is not None
    assert music_plan["audio_cues"][0]["kind"] == "bgm_entry"
    assert cues[0]["kind"] == "bgm_entry"
    assert cues[1]["kind"] == "sfx_overlay"


def test_plan_local_music_entry_respects_main_only_material_usage() -> None:
    plan = asyncio.run(
        plan_local_music_entry(
            music_plan={"asset_id": "music-a", "path": "bgm.mp3"},
            subtitle_items=[
                {"start_time": 0.0, "end_time": 2.4, "text_final": "开场先铺一下问题"},
                {"start_time": 2.8, "end_time": 5.6, "text_final": "这里直接把重点说完。"},
            ],
            content_profile={
                "content_kind": "tutorial",
                "source_context": {
                    "product_controls": {
                        "edit_mode": "tutorial",
                        "automation_level": "standard",
                        "material_usage": "main_only",
                    }
                },
            },
            timeline_analysis={"hook_end_sec": 2.0, "strategy_type": "step_demonstration"},
        )
    )

    assert plan is None
