from roughcut.review.content_understanding_evidence import build_evidence_bundle
from roughcut.review.content_understanding_infer import _build_content_understanding_prompt
from roughcut.review.content_understanding_schema import ContentSemanticFacts


def test_source_context_is_part_of_semantic_fact_inputs() -> None:
    bundle = build_evidence_bundle(
        source_name="merged_3_傲雷掠夺者2mini战术手电开箱.mp4",
        transcript_excerpt="后面顺带说一下SK05的操作逻辑。",
        source_context={
            "video_description": "这条视频主要开箱傲雷掠夺者2mini战术手电。",
            "manual_video_summary": "主体是傲雷掠夺者2mini，SK05只是对比提及。",
        },
    )

    semantic_inputs = bundle["semantic_fact_inputs"]

    assert semantic_inputs["source_context"]["video_description"] == "这条视频主要开箱傲雷掠夺者2mini战术手电。"
    assert "视频说明: 这条视频主要开箱傲雷掠夺者2mini战术手电。" in semantic_inputs["editorial_context_lines"]
    assert "人工视频摘要: 主体是傲雷掠夺者2mini，SK05只是对比提及。" in semantic_inputs["editorial_context_lines"]
    assert any("掠夺者2mini" in token for token in semantic_inputs["entity_like_tokens"])


def test_content_understanding_prompt_requires_joint_reasoning() -> None:
    bundle = build_evidence_bundle(
        source_name="merged_3_傲雷掠夺者2mini战术手电开箱.mp4",
        transcript_excerpt="后面顺带说一下SK05的操作逻辑。",
        source_context={"video_description": "这条视频主要开箱傲雷掠夺者2mini战术手电。"},
    )

    prompt = _build_content_understanding_prompt(bundle, ContentSemanticFacts())

    assert "文件名、视频说明、人工摘要属于创作者给出的先验线索" in prompt
    assert "ASR 转写、字幕、OCR、画面语义属于实际内容证据" in prompt
    assert "这条视频主要开箱傲雷掠夺者2mini战术手电" in prompt
    assert "后面顺带说一下SK05的操作逻辑" in prompt
