from __future__ import annotations

import uuid

from roughcut.api.jobs import _build_smart_director_prompt_source_name
from roughcut.creative.smart_director import (
    SMART_DIRECTOR_ARTIFACT_TYPES,
    build_smart_director_asset_plan,
    build_smart_director_brief,
    build_smart_director_compose_plan,
    build_smart_director_music_plan,
    build_smart_director_review,
    build_smart_director_script_plan,
    build_smart_director_storyboard_plan,
    build_smart_director_voiceover_plan,
)
from roughcut.pipeline.orchestrator import SMART_DIRECTOR_PIPELINE_STEPS, create_job_steps


def test_create_job_steps_uses_smart_director_pipeline_for_smart_director_mode() -> None:
    job_id = uuid.uuid4()

    steps = create_job_steps(job_id, workflow_mode="smart_director")

    assert [step.step_name for step in steps] == SMART_DIRECTOR_PIPELINE_STEPS
    assert "probe" not in [step.step_name for step in steps]


def test_smart_director_builders_produce_complete_compose_contract() -> None:
    brief = build_smart_director_brief(
        job_id=str(uuid.uuid4()),
        source_name="smart_director_prompt.prompt",
        source_context={"source_kind": "prompt_only"},
        task_brief="做一条 60 秒的 AI 科普短片，解释手机夜景为什么会越拍越亮，9:16。",
        video_description=None,
        language="zh-CN",
        platform_targets=["douyin"],
    )
    script = build_smart_director_script_plan(brief)
    storyboard = build_smart_director_storyboard_plan(script)
    assets = build_smart_director_asset_plan(storyboard)
    voiceover = build_smart_director_voiceover_plan(script)
    music = build_smart_director_music_plan(script)
    compose = build_smart_director_compose_plan(
        script_plan=script,
        storyboard_plan=storyboard,
        asset_plan=assets,
        voiceover_plan=voiceover,
        music_plan=music,
    )
    review = build_smart_director_review(compose, assets)

    assert brief["schema"] == SMART_DIRECTOR_ARTIFACT_TYPES["director_brief"]
    assert brief["target"]["duration_sec"] == 60
    assert brief["target"]["aspect_ratio"] == "9:16"
    assert len(script["scenes"]) >= 3
    assert len(storyboard["scenes"]) == len(script["scenes"])
    assert len(assets["assets"]) == len(script["scenes"])
    assert len(voiceover["lines"]) == len(script["scenes"])
    assert compose["delivery"]["renderer"] == "hyperframes"
    assert review["status"] == "plan_ready"


def test_smart_director_prompt_source_name_is_stable_and_non_empty() -> None:
    source_name = _build_smart_director_prompt_source_name("做一条 30 秒短片")

    assert source_name.startswith("smart_director_")
    assert source_name.endswith(".prompt")
    assert _build_smart_director_prompt_source_name("做一条 30 秒短片") == source_name
