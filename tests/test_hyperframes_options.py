from roughcut.api.jobs import (
    _merge_hyperframes_capability_keys,
    _merge_hyperframes_enhancement_modes,
    _normalize_hyperframes_options_payload,
)
from roughcut import hyperframes


def test_hyperframes_options_default_all_visual_features_enabled() -> None:
    options = _normalize_hyperframes_options_payload(None)

    assert options == {
        "smart_effects": True,
        "subtitle_emphasis": True,
        "sound_cues": True,
        "progress_bar": True,
        "chapter_cards": True,
        "unified_subtitle_style": True,
    }


def test_hyperframes_options_promote_existing_task_modes() -> None:
    options = _normalize_hyperframes_options_payload('{"smart_effects": true, "sound_cues": true, "chapter_cards": true}')

    assert _merge_hyperframes_enhancement_modes([], options) == ["ai_effects"]
    assert _merge_hyperframes_capability_keys(["screen_focus"], options) == [
        "screen_focus",
        "chapter_cards",
        "local_audio_cues",
    ]


def test_hyperframes_chapter_cards_render_as_bottom_chapter_pills() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=30.0,
        focus_plan={"chapter_cards": [{"start_time": 3.0, "end_time": 6.0, "title": "快拆结构"}]},
    )

    chapter_elements = [
        item for item in plan["elements"] if item.get("track") == "chapter_cards"
    ]

    assert chapter_elements
    assert chapter_elements[0]["style"] == "bottom_chapter_pill"
    assert chapter_elements[0]["position"]["y"] >= 980
