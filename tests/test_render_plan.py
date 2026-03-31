from __future__ import annotations

import uuid

from roughcut.edit.render_plan import (
    build_ai_effect_render_plan,
    build_avatar_render_plan,
    build_plain_render_plan,
    build_render_plan,
    build_smart_editing_accents,
)


def test_build_render_plan_defaults():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(editorial_timeline_id=timeline_id)

    assert plan["editorial_timeline_id"] == str(timeline_id)
    assert plan["workflow_preset"] == "unboxing_standard"
    assert plan["loudness"]["target_lufs"] == -16.0
    assert plan["loudness"]["peak_limit"] == -2.0
    assert plan["voice_processing"]["noise_reduction"] is True
    assert plan["subtitles"]["style"] == "bold_yellow_outline"
    assert plan["cover"]["variant_count"] == 5
    assert plan["intro"] is None
    assert plan["outro"] is None
    assert plan["insert"] is None
    assert plan["watermark"] is None
    assert plan["music"] is None
    assert plan["creative_profile"] is None
    assert plan["ai_director"] is None
    assert plan["avatar_commentary"] is None
    assert plan["editing_accents"]["style"] == "smart_effect_rhythm"
    assert plan["editing_accents"]["emphasis_overlays"] == []


def test_build_render_plan_custom():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(
        editorial_timeline_id=timeline_id,
        workflow_preset="unboxing_upgrade",
        target_lufs=-16.0,
        noise_reduction=False,
        subtitle_style="white_minimal",
        cover_style="tactical_neon",
        creative_profile={"workflow_mode": "standard_edit", "enhancement_modes": ["ai_director"]},
        ai_director_plan={"voiceover_segments": [{"segment_id": "director_hook"}]},
        avatar_commentary_plan={"segments": [{"segment_id": "avatar_1"}]},
    )
    assert plan["workflow_preset"] == "unboxing_upgrade"
    assert plan["loudness"]["target_lufs"] == -16.0
    assert plan["voice_processing"]["noise_reduction"] is False
    assert plan["subtitles"]["style"] == "white_minimal"
    assert plan["cover"]["style"] == "tactical_neon"
    assert plan["creative_profile"]["enhancement_modes"] == ["ai_director"]
    assert plan["ai_director"]["voiceover_segments"][0]["segment_id"] == "director_hook"
    assert plan["avatar_commentary"]["segments"][0]["segment_id"] == "avatar_1"


def test_build_smart_editing_accents_limits_count_and_prefers_strong_lines():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 5.0, "end": 9.0},
        {"start": 11.0, "end": 15.0},
        {"start": 15.2, "end": 18.0},
    ]
    subtitle_items = [
        {"start_time": 1.0, "end_time": 2.4, "text_final": "这点一定要注意"},
        {"start_time": 9.8, "end_time": 11.0, "text_final": "直接上 PRO"},
        {"start_time": 18.5, "end_time": 19.5, "text_final": "普通描述一下"},
    ]

    accents = build_smart_editing_accents(
        keep_segments=keep_segments,
        subtitle_items=subtitle_items,
    )

    assert accents["transitions"]["enabled"] is True
    assert accents["transitions"]["boundary_indexes"] == [0, 1]
    assert len(accents["emphasis_overlays"]) == 2
    assert accents["emphasis_overlays"][0]["text"] == "这点一定要注意"
    assert accents["emphasis_overlays"][1]["text"] == "直接上PRO"
    assert len(accents["sound_effects"]) == 2


def test_build_plain_render_plan_disables_packaging_and_accents():
    plan = build_plain_render_plan(
        {
            "intro": {"path": "intro.mp4"},
            "outro": {"path": "outro.mp4"},
            "insert": {"path": "insert.mp4"},
            "watermark": {"path": "mark.png"},
            "music": {"path": "music.mp3"},
            "avatar_commentary": {"mode": "full_track_audio_passthrough"},
            "editing_accents": {
                "style": "restrained",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意", "start_time": 1.0, "end_time": 2.0}],
                "sound_effects": [{"start_time": 1.0}],
            },
        }
    )

    assert plan["intro"] is None
    assert plan["outro"] is None
    assert plan["insert"] is None
    assert plan["watermark"] is None
    assert plan["music"] is None
    assert plan["subtitles"] is None
    assert plan["avatar_commentary"] is None
    assert plan["editing_accents"]["transitions"]["enabled"] is False
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == []
    assert plan["editing_accents"]["emphasis_overlays"] == []
    assert plan["editing_accents"]["sound_effects"] == []


def test_build_avatar_render_plan_keeps_packaging_but_disables_accents():
    plan = build_avatar_render_plan(
        {
            "intro": {"path": "intro.mp4"},
            "subtitles": {"style": "bold_yellow_outline"},
            "avatar_commentary": {"mode": "full_track_audio_passthrough", "integration_mode": "picture_in_picture"},
            "editing_accents": {
                "style": "restrained",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意"}],
                "sound_effects": [{"start_time": 1.0}],
            },
        }
    )

    assert plan["intro"] == {"path": "intro.mp4"}
    assert plan["subtitles"] == {"style": "bold_yellow_outline"}
    assert plan["avatar_commentary"]["integration_mode"] == "picture_in_picture"
    assert plan["editing_accents"]["transitions"]["enabled"] is False
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == []
    assert plan["editing_accents"]["emphasis_overlays"] == []
    assert plan["editing_accents"]["sound_effects"] == []


def test_build_ai_effect_render_plan_drops_avatar_but_keeps_effects():
    plan = build_ai_effect_render_plan(
        {
            "avatar_commentary": {"mode": "full_track_audio_passthrough"},
            "editing_accents": {
                "style": "restrained",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意"}],
                "sound_effects": [{"start_time": 1.0}],
            },
        }
    )

    assert plan["avatar_commentary"] is None
    assert plan["editing_accents"]["transitions"]["enabled"] is True
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == [0]
    assert plan["editing_accents"]["emphasis_overlays"] == [{"text": "注意"}]
