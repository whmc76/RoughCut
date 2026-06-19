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


def test_hyperframes_chapters_derive_from_subtitle_section_roles() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=24.0,
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "先看整体", "subtitle_section_role": "hook"},
            {"start_time": 3.0, "end_time": 6.0, "text_final": "这里看结构", "subtitle_section_role": "detail"},
            {"start_time": 8.0, "end_time": 14.0, "text_final": "开始上手展示", "subtitle_section_role": "body"},
            {"start_time": 18.0, "end_time": 22.0, "text_final": "最后总结", "subtitle_section_role": "cta"},
        ],
    )

    segments = hyperframes.chapter_segments(plan)
    chapter_elements = [item for item in plan["elements"] if item.get("track") == "chapter_cards"]
    progress_elements = [item for item in plan["elements"] if item.get("track") == "progress_bar"]

    assert [item["role"] for item in segments] == ["hook", "detail", "body", "cta"]
    assert [item["title"].split()[0] for item in segments] == ["开场", "细节", "展示", "收尾"]
    assert len(chapter_elements) == 4
    assert progress_elements[0]["segments"] == segments


def test_hyperframes_chapters_fallback_to_section_choreography() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=12.0,
        section_choreography={
            "sections": [
                {"start_sec": 0.0, "end_sec": 3.0, "role": "hook"},
                {"start_sec": 3.0, "end_sec": 8.0, "role": "detail"},
                {"start_sec": 8.0, "end_sec": 12.0, "role": "cta"},
            ]
        },
    )

    segments = hyperframes.chapter_segments(plan)

    assert [item["role"] for item in segments] == ["hook", "detail", "cta"]
    assert [item["source"] for item in segments] == ["section_choreography"] * 3
