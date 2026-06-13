from roughcut.edit.local_focus_plan import build_local_focus_plan, normalize_timed_focus_spans
from roughcut.edit.packaging_timeline import (
    build_packaging_timeline_payload,
    packaging_timeline_chapter_cards,
    packaging_timeline_focus_events,
    packaging_timeline_focus_plan,
)
from roughcut.edit.render_plan import build_render_plan


def test_normalize_timed_focus_spans_orders_and_coerces_payload() -> None:
    spans = normalize_timed_focus_spans(
        [
            {"timestamp": "00:02-00:05", "text": "对比", "type": "comparison", "start_time": 2.0, "end_time": 5.0},
            {"timestamp": "00:00-00:02", "text": "开场结论", "type": "hook", "start_time": 0.0, "end_time": 2.0},
        ]
    )

    assert spans[0]["type"] == "hook"
    assert spans[1]["type"] == "comparison"


def test_build_local_focus_plan_from_content_understanding_spans() -> None:
    focus_plan = build_local_focus_plan(
        content_profile={
            "content_understanding": {
                "video_type": "tutorial",
                "timed_focus_spans": [
                    {"timestamp": "00:00-00:02", "text": "先讲结论", "type": "hook", "start_time": 0.0, "end_time": 2.0},
                    {"timestamp": "00:02-00:05", "text": "这里做对比", "type": "comparison", "start_time": 2.0, "end_time": 5.0},
                ]
            }
        },
        timeline_analysis={"hook_end_sec": 2.0},
    )

    assert focus_plan is not None
    assert focus_plan["focus_events"][0]["event_type"] == "hook_focus"
    assert focus_plan["focus_events"][1]["event_type"] == "comparison_focus"
    assert focus_plan["chapter_cards"][0]["card_type"] == "opening"


def test_build_local_focus_plan_returns_none_for_non_tutorial_profiles() -> None:
    focus_plan = build_local_focus_plan(
        content_profile={
            "content_kind": "commentary",
            "content_understanding": {
                "timed_focus_spans": [
                    {"timestamp": "00:00-00:02", "text": "先讲结论", "type": "hook", "start_time": 0.0, "end_time": 2.0}
                ]
            },
        },
        timeline_analysis={"hook_end_sec": 2.0},
    )

    assert focus_plan is None


def test_build_local_focus_plan_allows_step_demonstration_strategy_without_content_kind() -> None:
    focus_plan = build_local_focus_plan(
        content_profile={
            "strategy_profile": {"strategy_type": "step_demonstration"},
            "content_understanding": {
                "timed_focus_spans": [
                    {"timestamp": "00:00-00:02", "text": "先讲结论", "type": "hook", "start_time": 0.0, "end_time": 2.0}
                ]
            },
        },
        timeline_analysis={"hook_end_sec": 2.0},
    )

    assert focus_plan is not None
    assert focus_plan["focus_events"][0]["event_type"] == "hook_focus"


def test_packaging_timeline_focus_readers_return_shared_focus_contract() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        focus_plan={
            "focus_events": [{"event_type": "screen_focus", "start_time": 1.0, "end_time": 2.0, "text": "重点按钮"}],
            "chapter_cards": [{"start_time": 0.0, "end_time": 2.0, "title": "开场重点"}],
        },
    )
    packaging_timeline = build_packaging_timeline_payload(plan)

    assert packaging_timeline_focus_plan(packaging_timeline) is not None
    assert packaging_timeline_focus_events(packaging_timeline)[0]["event_type"] == "screen_focus"
    assert packaging_timeline_chapter_cards(packaging_timeline)[0]["title"] == "开场重点"
