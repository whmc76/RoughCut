from __future__ import annotations

from roughcut.pipeline.rerun_actions import QUALITY_RERUN_STEPS, rerun_chain_from_step


def test_extract_audio_is_supported_recovery_rerun_start() -> None:
    chain = rerun_chain_from_step("extract_audio")

    assert "extract_audio" in QUALITY_RERUN_STEPS
    assert chain[:3] == ["extract_audio", "transcribe", "subtitle_postprocess"]
    assert chain[-4:] == ["edit_plan", "render", "final_review", "platform_package"]


def test_transcribe_is_supported_recovery_rerun_start() -> None:
    chain = rerun_chain_from_step("transcribe")

    assert "transcribe" in QUALITY_RERUN_STEPS
    assert chain[:2] == ["transcribe", "subtitle_postprocess"]
    assert chain[chain.index("content_profile") + 1] == "summary_review"
    assert chain[-4:] == ["edit_plan", "render", "final_review", "platform_package"]


def test_content_profile_rerun_revisits_summary_review_gate() -> None:
    chain = rerun_chain_from_step("content_profile")

    assert "summary_review" in QUALITY_RERUN_STEPS
    assert chain[:2] == ["content_profile", "summary_review"]
