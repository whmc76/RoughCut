from roughcut.prompts.edit_decision import (
    build_high_risk_cut_review_prompt,
    build_multimodal_trim_review_batch_prompt,
    build_waste_segment_discovery_prompt,
)


def test_high_risk_cut_review_prompt_requires_contextual_llm_judgment() -> None:
    messages = build_high_risk_cut_review_prompt(
        source_meta={"source_name": "demo.mp4"},
        candidates=[{"candidate_id": "c1", "start": 0.0, "end": 4.0, "reason": "rollback_instruction"}],
    )
    content = "\n".join(str(message["content"]) for message in messages)

    assert "绝不能按固定词表或关键词直接匹配" in content
    assert "基于候选片段、前后字幕、转写上下文和视频语义做整体判断" in content


def test_multimodal_trim_prompt_rejects_keyword_matching() -> None:
    prompt = build_multimodal_trim_review_batch_prompt(
        source_meta={"source_name": "demo.mp4"},
        candidates=[{"candidate_id": "c1", "start": 0.0, "end": 4.0, "reason": "low_signal_subtitle"}],
    )

    assert "绝不能用固定关键词或词表直接判定" in prompt
    assert "结合画面、候选文本和前后上下文判断" in prompt


def test_waste_segment_discovery_prompt_requires_llm_semantic_judgment() -> None:
    messages = build_waste_segment_discovery_prompt(
        source_meta={"source_name": "demo.mp4"},
        subtitle_context=[{"start": 0.0, "end": 2.0, "text": "这里打不开我再试一下"}],
    )
    content = "\n".join(str(message["content"]) for message in messages)

    assert "主动发现废片候选" in content
    assert "绝不能按固定词表或关键词直接匹配" in content
    assert "候选边界要覆盖应删除的完整废片段" in content
