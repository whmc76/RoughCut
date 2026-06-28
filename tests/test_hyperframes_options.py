from roughcut.api.jobs import (
    _merge_hyperframes_capability_keys,
    _merge_hyperframes_enhancement_modes,
    _normalize_hyperframes_options_payload,
)
from roughcut import hyperframes


def test_hyperframes_options_default_keeps_progress_bar_as_optional_addon() -> None:
    options = _normalize_hyperframes_options_payload(None)

    assert options == {
        "smart_effects": True,
        "subtitle_emphasis": True,
        "sound_cues": True,
        "progress_bar": False,
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


def test_hyperframes_progress_bar_is_absent_until_selected() -> None:
    default_plan = hyperframes.build_render_plan(width=1920, height=1080, duration_sec=30.0)
    enabled_plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=30.0,
        options={"progress_bar": True},
    )

    assert not hyperframes.progress_bar_enabled(default_plan)
    assert [item for item in default_plan["elements"] if item.get("track") == "progress_bar"] == []
    assert hyperframes.progress_bar_enabled(enabled_plan)
    assert [item for item in enabled_plan["elements"] if item.get("track") == "progress_bar"]


def test_hyperframes_chapters_derive_from_subtitle_section_roles() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=24.0,
        options={"progress_bar": True},
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
    assert [item["title"] for item in segments] == ["先看整体", "这里看结构", "开始上手展示", "最后总结"]
    assert len(chapter_elements) == 4
    assert chapter_elements[1]["start_sec"] == 3.0
    assert chapter_elements[1]["end_sec"] == 6.0
    assert chapter_elements[2]["start_sec"] == 8.0
    assert chapter_elements[2]["end_sec"] == 14.0
    assert progress_elements[0]["segments"] == segments


def test_hyperframes_chapters_fallback_to_section_choreography() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=12.0,
        section_choreography={
            "sections": [
                {"start_sec": 0.0, "end_sec": 3.0, "role": "hook", "summary": "内部摘要不应上屏"},
                {"start_sec": 3.0, "end_sec": 8.0, "role": "detail", "creative_rationale": "细节段优先保留近景"},
                {"start_sec": 8.0, "end_sec": 12.0, "role": "cta", "summary": "结尾行动引导"},
            ]
        },
    )

    segments = hyperframes.chapter_segments(plan)

    assert [item["role"] for item in segments] == ["hook", "detail", "cta"]
    assert [item["title"] for item in segments] == ["开场", "细节", "总结"]
    assert [item["source"] for item in segments] == ["section_choreography"] * 3
    assert all("优先保留" not in item["title"] for item in segments)


def test_hyperframes_chapters_use_explicit_section_choreography_titles() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=12.0,
        section_choreography={
            "sections": [
                {"start_sec": 0.0, "end_sec": 3.0, "role": "hook", "chapter_title": "开箱先看核心变化"},
                {"start_sec": 3.0, "end_sec": 8.0, "role": "detail", "chapter_title": "结构和背负细节"},
                {"start_sec": 8.0, "end_sec": 12.0, "role": "cta", "chapter_title": "购买建议总结"},
            ]
        },
    )

    segments = hyperframes.chapter_segments(plan)

    assert [item["title"] for item in segments] == ["开箱先看核心变化", "结构和背负细节", "购买建议总结"]
    assert [item["source"] for item in segments] == ["section_choreography"] * 3


def test_hyperframes_chapters_fallback_to_plain_subtitle_timeline() -> None:
    plan = hyperframes.build_render_plan(
        width=1920,
        height=1080,
        duration_sec=24.0,
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "先看整体变化"},
            {"start_time": 3.0, "end_time": 5.0, "text_final": "外观结构细节"},
            {"start_time": 8.0, "end_time": 10.0, "text_final": "容量展示"},
            {"start_time": 12.0, "end_time": 15.0, "text_final": "背负体验"},
            {"start_time": 18.0, "end_time": 22.0, "text_final": "最后总结建议"},
        ],
    )

    segments = hyperframes.chapter_segments(plan)

    assert len(segments) >= 2
    assert {item["source"] for item in segments} == {"subtitle_timeline_fallback"}
    assert segments[0]["title"] == "先看整体变化"
    assert segments[-1]["title"] in {"背负体验", "最后总结建议"}
