from __future__ import annotations

import argparse
import json
from pathlib import Path

import scripts.build_script_footage_remix_samples as script_footage_samples
from roughcut.remix.alignment import (
    TTS_ALIGNMENT_SOURCE,
    audit_subtitle_timing_alignment,
    build_asr_aligned_subtitle_timings,
    canonical_coverage,
    evaluate_tts_asr_alignment,
    normalize_eval_text,
)
from roughcut.remix.batch_report import (
    BATCH_REPORT_SCHEMA,
    build_batch_report_payload,
    render_batch_report_markdown,
    render_methodology_report_markdown,
)
from roughcut.remix.caption_packager import CAPTION_PACKAGE_SCHEMA, build_caption_package, wrap_ass_text
from roughcut.remix.contracts import AsrToken, SourceAnchor, SubtitleTiming
from roughcut.remix.edit_plan import EDIT_PLAN_SCHEMA, build_clip_entries, build_edit_plan_payload
from roughcut.remix.qa import evaluate_episode_report
from roughcut.remix.review_frames import REVIEW_FRAMES_SCHEMA, build_review_frames_manifest, review_frame_timestamps
from roughcut.remix import scene_index as remix_scene_index
from roughcut.remix.scene_index import build_scene_index_payload, match_clip_to_scene, normalize_scene_spans
from roughcut.remix.script_topics import (
    TOPIC_PLAN_SCHEMA,
    build_topic_chunks,
    build_topic_plan_payload,
    extract_story_keywords,
)
from roughcut.remix.source_selection import evaluate_source_asr_index, select_source_asr_clip_starts
from roughcut.remix.contracts import SceneSpan
from roughcut.remix.creator_profile import creator_caption_style_defaults, creator_tts_defaults, load_creator_profile
from roughcut.remix.hyperframes import HYPERFRAMES_ENGINE, HYPERFRAMES_PLAN_SCHEMA


def _tts_voice_report_fields() -> dict[str, object]:
    return {
        "tts_request_metadata_path": "tts_request.json",
        "tts_provider": "moss_tts_local",
        "tts_mode": "moss_voice_clone",
        "tts_reference_history_path": "/app/data/tools/reference-uploads/读绘本试音-2.mp3",
        "tts_prompt_text": "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
        "tts_voice_signature": "voice-signature",
    }


def _hyperframes_report_fields(*, subtitle_events: int = 42, packaging_events: int = 14) -> dict[str, object]:
    return {
        "packaging_framework": HYPERFRAMES_ENGINE,
        "hyperframes_enabled": True,
        "hyperframes_plan_schema": HYPERFRAMES_PLAN_SCHEMA,
        "hyperframes_element_count": subtitle_events + packaging_events,
        "hyperframes_effect_count": max(30, subtitle_events + packaging_events),
        "packaging_audio_cue_count": 9,
        "semantic_packaging_source": "llm_script_packaging",
        "semantic_packaging_llm_reviewed": True,
        "source_bridge_count": 0,
    }


def _original_audio_no_insert_report_fields() -> dict[str, object]:
    return {
        "original_audio_intent_analysis_path": "original_audio_intent.json",
        "original_audio_intent_source": "llm_script_intent",
        "original_audio_intent_decision": "no_insert",
        "original_audio_intent_confidence": 0.0,
        "original_audio_intent_llm_reviewed": True,
        "original_audio_source_mapping_path": "",
        "original_audio_source_mapping_source": "",
        "original_audio_source_mapping_llm_reviewed": True,
        "original_audio_reference_intent_count": 0,
        "original_audio_insert_count": 0,
        "original_audio_insert_total_duration_sec": 0.0,
        "original_audio_insertions_path": "",
        "original_audio_visual_bridge_count": 0,
    }


def _passing_report(episode: int) -> dict[str, object]:
    return {
        "episode": episode,
        "title": f"第{episode}集",
        "build_status": "done",
        "qa_status": "pass",
        "qa_issue_count": 0,
        "output_path": "final.mp4",
        "narration_path": "narration.wav",
        "render_narration_path": "narration_clean.wav",
        **_tts_voice_report_fields(),
        "subtitle_path": "subtitle.ass",
        "caption_package_path": "caption_package.json",
        "semantic_packaging_plan_path": "semantic_caption_packaging.json",
        "subtitle_timing_audit_path": "subtitle_timing_audit.json",
        "topic_plan_path": "topic_plan.json",
        "edit_plan_path": "edit_plan.json",
        "qa_report_path": "qa_report.json",
        "review_frames_manifest_path": "review_frames.json",
        "scene_index_path": "scene_index.json",
        "tts_asr_evidence_path": "tts_asr.json",
        "source_asr_index_path": "source_asr.json",
        "output_duration_sec": 136.0,
        "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
        "subtitle_text_coverage": 1.0,
        "subtitle_style_profile": "children_storybook_v1",
        **_hyperframes_report_fields(),
        "max_subtitle_lines_per_event": 2,
        "max_subtitle_line_chars": 17,
        "subtitle_timing_alignment_status": "pass",
        "subtitle_timing_unmatched_count": 0,
        "subtitle_timing_bad_drift_count": 0,
        "subtitle_timing_max_abs_start_drift_sec": 0.04,
        "subtitle_timing_max_abs_end_drift_sec": 0.12,
        "subtitle_timing_audit_path": "subtitle_timing_audit.json",
        "tts_asr_coverage": 0.98,
        "source_asr_anchor_count": 14,
        **_original_audio_no_insert_report_fields(),
        "theme_banner_count": 3,
        "keyword_sticker_count": 3,
        "watermark_event_count": 1,
        "emphasis_keyword_count": 3,
        "motion_effect_count": 16,
        "animated_subtitle_event_count": 10,
        "animated_packaging_event_count": 8,
        "review_frame_count": 5,
    }


def _semantic_packaging_plan(matched_text: str) -> dict[str, object]:
    return {
        "source": "llm_script_packaging",
        "llm_reviewed": True,
        "opening_title": "看见感受",
        "closing_title": "先接住孩子",
        "subtitle_emphasis_keywords": [
            {"phrase": "孩子", "matched_text": matched_text, "reason": "主体"},
            {"phrase": "看见", "matched_text": matched_text, "reason": "核心观点"},
            {"phrase": "愿意", "matched_text": matched_text, "reason": "关键判断"},
        ],
        "theme_banners": [
            {"phrase": "看见感受", "matched_text": matched_text, "reason": "主题"},
            {"phrase": "先别急", "matched_text": matched_text, "reason": "节奏"},
            {"phrase": "给出选择", "matched_text": matched_text, "reason": "方法"},
        ],
        "keyword_bubbles": [
            {"phrase": "先看见", "matched_text": matched_text, "reason": "提示"},
            {"phrase": "别硬推", "matched_text": matched_text, "reason": "提示"},
            {"phrase": "慢一点", "matched_text": matched_text, "reason": "提示"},
        ],
        "impact_events": [
            {"phrase": "看见", "matched_text": matched_text, "reason": "重点"},
            {"phrase": "愿意", "matched_text": matched_text, "reason": "重点"},
            {"phrase": "选择", "matched_text": matched_text, "reason": "重点"},
        ],
        "pulse_chips": [
            {"phrase": "感受", "matched_text": matched_text, "reason": "辅助"},
            {"phrase": "边界", "matched_text": matched_text, "reason": "辅助"},
            {"phrase": "选择", "matched_text": matched_text, "reason": "辅助"},
        ],
    }


def _tone_with_silence_samples(*, sample_rate: int = 24000, tone_sec: float, silence_sec: float) -> list[int]:
    tone_count = int(sample_rate * tone_sec)
    silence_count = int(sample_rate * silence_sec)
    samples: list[int] = []
    samples.extend([9000 if index % 2 == 0 else -9000 for index in range(tone_count)])
    samples.extend([0] * silence_count)
    return samples


def test_tts_asr_alignment_coverage_accepts_near_exact_tts_text() -> None:
    coverage = canonical_coverage("孩子可以说不，这不是不听话。", "孩子可以说不这不是不听话")
    assert coverage >= 0.95


def test_asr_subtitle_timing_uses_lcs_when_asr_omits_characters() -> None:
    chunks = ["爸爸自己说可以的，结果怎么又不行了？", "妈妈要说实话。"]
    asr_text = "爸爸自己说可以结果怎么又不行妈妈要说实话"
    tokens = [
        AsrToken(text=char, start_sec=index * 0.2, end_sec=(index + 1) * 0.2)
        for index, char in enumerate(asr_text)
    ]

    timings = build_asr_aligned_subtitle_timings(chunks, tokens, duration_sec=8.0)
    audit = audit_subtitle_timing_alignment(timings, tokens)

    assert len(timings) == 2
    assert timings[0].start_sec < 0.25
    assert timings[1].start_sec > timings[0].start_sec
    assert audit["status"] == "pass"
    assert audit["bad_drift_count"] == 0


def test_caption_wrap_never_truncates_subtitle_text() -> None:
    text = "爸爸自己说可以的，结果怎么又不行了？妈妈要说实话。"

    wrapped = wrap_ass_text(text, max_line_chars=10)

    assert r"\N" in wrapped
    assert normalize_eval_text(wrapped.replace(r"\N", "")) == normalize_eval_text(text)


def test_caption_wrap_keeps_display_within_two_lines_when_chunk_fits() -> None:
    text = "孩子们很快把这些展示品变成了自己的家"

    wrapped = wrap_ass_text(text, max_line_chars=17)

    lines = wrapped.split(r"\N")
    assert len(lines) <= 2
    assert max(len(line) for line in lines) <= 17
    assert normalize_eval_text(wrapped.replace(r"\N", "")) == normalize_eval_text(text)


def test_moss_segment_pacing_preserves_minimum_output_duration(tmp_path: Path) -> None:
    segments = []
    for index in range(1, 6):
        path = tmp_path / f"segment_{index}.wav"
        script_footage_samples.write_pcm16_mono(
            path,
            _tone_with_silence_samples(tone_sec=20.0, silence_sec=5.0),
            24000,
        )
        segments.append({"index": index, "text": f"第 {index} 段", "path": str(path)})

    stats, timings = script_footage_samples.build_tts_segment_paced_audio(
        {"live_segments": segments},
        tmp_path / "paced.wav",
        work_dir=tmp_path / "work",
        min_output_duration_sec=120.0,
        force=True,
    )

    assert stats.original_duration_sec == 125.0
    assert stats.output_duration_sec >= 120.0
    assert timings[-1].end_sec >= 120.0


def test_resolve_script_text_for_tts_preserves_full_script_by_default() -> None:
    text = "第一句是成稿。\n第二句不能被删。\n第三句也必须保留。"
    args = argparse.Namespace(max_script_chars=0, condense_script=False, no_condense=False)

    resolved = script_footage_samples.resolve_script_text_for_tts(text, args=args, target_chars=10)

    assert resolved == text


def test_resolve_script_text_for_tts_blocks_character_truncation() -> None:
    args = argparse.Namespace(max_script_chars=12, condense_script=False, no_condense=False)

    try:
        script_footage_samples.resolve_script_text_for_tts("这是一段成稿文案。", args=args, target_chars=10)
    except RuntimeError as exc:
        assert "must not be truncated" in str(exc)
    else:
        raise AssertionError("expected max-script-chars to be rejected")


def test_resolve_script_text_for_tts_condenses_only_when_explicitly_enabled() -> None:
    text = "第一句是成稿。第二句不能默认被删。第三句也必须保留。第四句测试显式压缩。"
    default_args = argparse.Namespace(max_script_chars=0, condense_script=False, no_condense=False)
    condense_args = argparse.Namespace(max_script_chars=0, condense_script=True, no_condense=False)

    assert script_footage_samples.resolve_script_text_for_tts(text, args=default_args, target_chars=10) == text
    assert script_footage_samples.resolve_script_text_for_tts(text, args=condense_args, target_chars=10) != text


def test_tts_wait_timeout_scales_for_moss_segments() -> None:
    long_text = "育" * 4800

    timeout = script_footage_samples.resolve_tts_wait_timeout_seconds(long_text, base_timeout_sec=300.0)

    assert timeout == 120.0 + 40.0 * 90.0


def test_tts_request_metadata_reuse_requires_matching_voice_signature(tmp_path: Path) -> None:
    expected = script_footage_samples.build_tts_request_metadata(
        "同一段文案",
        provider="moss_tts_local",
        mode="moss_voice_clone",
        reference_history_path="/app/data/tools/reference-uploads/读绘本试音-2.mp3",
        prompt_text="明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
    )
    wrong_voice = script_footage_samples.build_tts_request_metadata(
        "同一段文案",
        provider="cosyvoice3",
        mode="instruct2",
        reference_history_path="/app/data/tools/reference-uploads/读绘本试音-2.mp3",
        prompt_text="明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
    )
    metadata_path = tmp_path / "tts_request.json"
    metadata_path.write_text(
        '{"schema":"roughcut.remix.tts_request.v1","request":' + json.dumps(wrong_voice, ensure_ascii=False) + "}",
        encoding="utf-8",
    )

    assert script_footage_samples.load_matching_tts_request_metadata(metadata_path, expected) is None


def test_tts_history_reuse_rejects_same_text_with_wrong_voice_provider() -> None:
    expected = script_footage_samples.build_tts_request_metadata(
        "同一段文案",
        provider="moss_tts_local",
        mode="moss_voice_clone",
        reference_history_path="/app/data/tools/reference-uploads/读绘本试音-2.mp3",
        prompt_text="明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
    )
    payload = {
        "request": {
            "text": "同一段文案",
            "provider": "cosyvoice3",
            "mode": "instruct2",
            "reference_path": "/app/data/tools/reference-uploads/读绘本试音-2.mp3",
            "prompt_text": "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
        },
        "result": {"audio_url": "/api/v1/tools/artifacts/tts/wrong.wav"},
    }

    assert script_footage_samples.tts_run_payload_matches_request(payload, expected) is False


def test_tts_history_reuse_accepts_reference_audio_from_result_payload() -> None:
    expected = script_footage_samples.build_tts_request_metadata(
        "同一段文案",
        provider="moss_tts_local",
        mode="moss_voice_clone",
        reference_history_path="/app/data/tools/reference-uploads/读绘本试音-2.mp3",
        prompt_text="明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
    )
    payload = {
        "request": {
            "text": "同一段 文案",
            "provider": "moss_tts_local",
            "mode": "moss_voice_clone",
            "prompt_text": "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。",
        },
        "result": {
            "reference_audio": "/app/data/tools/reference-uploads/读绘本试音-2.mp3",
            "audio_url": "/api/v1/tools/artifacts/tts/right.wav",
        },
    }

    assert script_footage_samples.tts_run_payload_matches_request(payload, expected) is True


def test_tts_defaults_to_no_reference_moss_direct_without_creator_voice() -> None:
    metadata = script_footage_samples.build_tts_request_metadata(
        "同一段文案",
        provider="moss_tts_local",
        mode="",
        reference_history_path="",
        prompt_text="",
    )

    assert metadata["mode"] == "moss_direct_tts"
    assert metadata["reference_history_path"] == ""


def test_episode_report_accepts_no_reference_moss_direct_tts() -> None:
    report = {
        **_passing_report(1),
        "tts_provider": "moss_tts_local",
        "tts_mode": "moss_direct_tts",
        "tts_reference_history_path": "",
        "tts_prompt_text": "",
    }

    result = evaluate_episode_report(report)

    assert not any(issue.code in {"remix_tts_moss_mode_invalid", "remix_tts_reference_missing"} for issue in result.issues)


def test_jenny_baby_creator_profile_binds_default_moss_voice() -> None:
    profile = load_creator_profile(repo_root=Path.cwd(), slug="jenny_baby")

    defaults = creator_tts_defaults(profile)
    caption_defaults = creator_caption_style_defaults(profile)

    assert profile is not None
    assert profile["name"] == "珍妮斯baby"
    assert defaults["provider"] == "moss_tts_local"
    assert defaults["mode"] == "moss_voice_clone"
    assert defaults["reference_history_path"] == "/app/data/tools/reference-uploads/读绘本试音-2.mp3"
    assert defaults["prompt_text"] == "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。"
    assert caption_defaults["subtitle_style_profile"] == "children_storybook_v1"
    assert profile["remix_task_bindings"][0]["task_id"] == "bluey_script_footage_remix"
    assert profile["remix_task_bindings"][0]["production_manifest_path"] == (
        "data/remix_production_tasks/jenny_baby_bluey_pending.json"
    )


def test_bluey_builder_applies_creator_tts_defaults() -> None:
    args = argparse.Namespace(
        creator_profile="jenny_baby",
        creator_profile_path=None,
        tts_provider="moss_tts_local",
        tts_mode="",
        reference_history_path="",
        prompt_text=script_footage_samples.DEFAULT_TTS_PROMPT_TEXT,
        subtitle_style_profile="",
    )

    profile = script_footage_samples.apply_creator_profile_defaults(args)

    assert profile is not None
    assert args.tts_provider == "moss_tts_local"
    assert args.tts_mode == "moss_voice_clone"
    assert args.reference_history_path == "/app/data/tools/reference-uploads/读绘本试音-2.mp3"
    assert args.prompt_text == "明亮互动版，小朋友们看这里，这是什么颜色呢？对啦，是黄色，黄。"
    assert args.subtitle_style_profile == "children_storybook_v1"


def test_production_manifest_applies_creator_profile_default() -> None:
    args = argparse.Namespace(
        production_manifest=Path("data/remix_production_tasks/jenny_baby_bluey_pending.json"),
        creator_profile="",
        creator_profile_path=None,
        tts_provider="moss_tts_local",
        tts_mode="",
        reference_history_path="",
        prompt_text=script_footage_samples.DEFAULT_TTS_PROMPT_TEXT,
        subtitle_style_profile="",
    )

    script_footage_samples.apply_production_manifest_defaults(args)
    profile = script_footage_samples.apply_creator_profile_defaults(args)

    assert args.creator_profile == "jenny_baby"
    assert profile is not None
    assert args.tts_mode == "moss_voice_clone"
    assert args.reference_history_path == "/app/data/tools/reference-uploads/读绘本试音-2.mp3"


def test_bluey_production_manifest_selects_pending_second_season_tasks() -> None:
    manifest_path = Path("data/remix_production_tasks/jenny_baby_bluey_pending.json")
    episodes = script_footage_samples.load_production_manifest_episodes(manifest_path, status="pending")

    completed = {1, 11, 20, 21, 22, 25, 32, 34, 43, 44, 46, 47, 50}
    assert len(episodes) == 39
    assert episodes[:5] == [2, 3, 4, 5, 6]
    assert episodes[-5:] == [45, 48, 49, 51, 52]
    assert not completed.intersection(episodes)


def test_batch_report_accepts_single_complete_sample_by_default() -> None:
    payload = build_batch_report_payload(
        [_passing_report(1)],
        source_root="F:/布鲁伊育儿节目",
        episodes=[1],
    )

    assert payload["schema"] == BATCH_REPORT_SCHEMA
    assert payload["sample_count"] == 1
    assert payload["min_sample_count"] == 1
    assert payload["pass_rate"] == 1.0
    assert payload["gate_passed"] is True
    assert payload["gate_reason"] == "passed"


def test_batch_report_can_require_ten_episodes_for_explicit_stability_run() -> None:
    payload = build_batch_report_payload(
        [_passing_report(episode) for episode in range(1, 4)],
        source_root="F:/布鲁伊育儿节目",
        episodes=[1, 2, 3],
        min_sample_count=10,
    )

    assert payload["schema"] == BATCH_REPORT_SCHEMA
    assert payload["sample_count"] == 3
    assert payload["min_sample_count"] == 10
    assert payload["pass_rate"] == 1.0
    assert payload["gate_passed"] is False
    assert payload["gate_reason"] == "evaluated_count_below_min:3<10"


def test_batch_report_passes_when_nine_of_ten_have_complete_evidence() -> None:
    reports = [_passing_report(episode) for episode in range(1, 11)]
    reports[-1]["qa_status"] = "warn"
    reports[-1]["qa_issue_count"] = 1

    payload = build_batch_report_payload(reports, source_root="F:/布鲁伊育儿节目", episodes=list(range(1, 11)))
    markdown = render_batch_report_markdown(payload)

    assert payload["sample_count"] == 10
    assert payload["qa_pass_count"] == 9
    assert payload["qa_warn_count"] == 1
    assert payload["accepted_count"] == 10
    assert payload["pass_rate"] == 1.0
    assert payload["gate_passed"] is True
    assert "| 10 | 第10集 | warn |" in markdown


def test_batch_report_rejects_any_hard_qa_failure_even_when_pass_rate_is_high() -> None:
    reports = [_passing_report(episode) for episode in range(1, 11)]
    reports[-1]["qa_status"] = "fail"
    reports[-1]["qa_issue_count"] = 1

    payload = build_batch_report_payload(reports, source_root="F:/布鲁伊育儿节目", episodes=list(range(1, 11)))

    assert payload["sample_count"] == 10
    assert payload["accepted_count"] == 9
    assert payload["pass_rate"] == 0.9
    assert payload["gate_passed"] is False
    assert payload["gate_reason"] == "qa_failed:1"


def test_batch_report_rejects_missing_asr_or_review_evidence() -> None:
    reports = [_passing_report(episode) for episode in range(1, 11)]
    reports[4]["tts_asr_evidence_path"] = ""
    reports[4]["review_frame_count"] = 0

    payload = build_batch_report_payload(reports, source_root="F:/布鲁伊育儿节目", episodes=list(range(1, 11)))

    assert payload["gate_passed"] is False
    assert payload["gate_reason"] == "required_evidence_missing"
    assert payload["required_evidence_failures"][0]["episode"] == 5
    assert "tts_asr_evidence_path" in payload["required_evidence_failures"][0]["missing"]
    assert "review_frames" in payload["required_evidence_failures"][0]["missing"]


def test_batch_report_can_verify_required_evidence_files_exist(tmp_path: Path) -> None:
    report = _passing_report(1)
    for key, value in list(report.items()):
        if value and (key.endswith("_path") or key in {"output_path", "narration_path", "render_narration_path", "subtitle_path"}):
            path = tmp_path / str(value)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            report[key] = str(path)
    reports = [dict(_passing_report(episode)) for episode in range(1, 11)]
    reports[0] = report

    missing_payload = build_batch_report_payload(
        reports,
        source_root="F:/布鲁伊育儿节目",
        episodes=list(range(1, 11)),
        verify_file_exists=True,
    )

    assert missing_payload["gate_passed"] is False
    assert any("file_missing" in item for item in missing_payload["required_evidence_failures"][1]["missing"])


def test_methodology_report_documents_asr_roles_and_quality_gates() -> None:
    markdown = render_methodology_report_markdown()

    assert "TTS-ASR" in markdown
    assert "Source-ASR" in markdown
    assert "qwen3_asr_forced_aligner_on_tts" in markdown
    assert "默认验收跑 1 集" in markdown
    assert "10 集压力测试" in markdown


def test_script_topic_chunks_preserve_order_and_target_count() -> None:
    text = "第一句讲问题。第二句讲剧情。第三句讲原因。第四句讲做法。第五句讲总结。"

    chunks = build_topic_chunks(text, target_count=3)

    assert len(chunks) == 3
    assert "".join(chunks) == text
    assert chunks[0].startswith("第一句")
    assert chunks[-1].endswith("第五句讲总结。")


def test_story_keywords_keep_title_and_domain_terms() -> None:
    keywords = extract_story_keywords("跳舞模式", "孩子可以说不，爸爸和布鲁伊都需要看见边界。")

    assert keywords[0] == "跳舞模式"
    assert "布鲁伊" in keywords
    assert "爸爸" in keywords
    assert "边界" in keywords


def test_topic_plan_payload_maps_topics_to_continuous_clips() -> None:
    payload = build_topic_plan_payload(
        episode=1,
        title="跳舞模式",
        question="孩子说好吧是不是真的愿意？",
        script_path="script.md",
        script_text="孩子说好吧不一定是真的愿意。大人要先看见边界。然后再给孩子一次选择机会。",
        clip_starts=[48.0, 72.0, 101.5],
        clip_durations=[12.0, 14.0, 16.0],
        source_asr_index_path="source_asr.json",
        min_topic_count=2,
        max_topic_count=3,
    )

    assert payload["schema"] == TOPIC_PLAN_SCHEMA
    assert payload["topic_count"] >= 2
    assert payload["topics"][0]["selected_clip"]["start_sec"] == 48.0
    assert payload["topics"][1]["selected_clip"]["duration_sec"] == 14.0
    assert "不逐句跳切" in payload["topics"][0]["visual_intent"]


def test_edit_plan_payload_records_topic_level_continuous_clips_and_scene_matches() -> None:
    payload = build_edit_plan_payload(
        episode=1,
        title="跳舞模式",
        source_video="source.mp4",
        topic_plan_path="topic_plan.json",
        scene_index_path="scene_index.json",
        source_asr_index_path="source_asr.json",
        narration_path="narration.wav",
        subtitle_path="subtitle.ass",
        montage_path="montage.mp4",
        output_path="final.mp4",
        clip_starts=[48.0, 72.0],
        clip_durations=[12.0, 14.0],
        segment_paths=["seg1.mp4", "seg2.mp4"],
        scene_spans=[
            SceneSpan(start_sec=40.0, end_sec=60.0),
            SceneSpan(start_sec=70.0, end_sec=90.0),
        ],
        video_transform={"crop": "crop=1440:810:180:50", "width": 1920, "height": 1080, "fps": 28},
    )

    assert payload["schema"] == EDIT_PLAN_SCHEMA
    assert payload["clip_count"] == 2
    assert payload["clips"][0]["selection_basis"] == "source_asr_topic_anchor_with_min_gap"
    assert payload["clips"][0]["scene_match"]["match_type"] == "contains_start"
    assert payload["clips"][1]["source_end_sec"] == 86.0
    assert payload["video_transform"]["width"] == 1920


def test_caption_package_records_default_jianying_style_packaging_counts() -> None:
    matched_text = "孩子说好吧，不一定是真的愿意。"
    package = build_caption_package(
        episode=1,
        title="跳舞模式",
        question="孩子说好吧是不是真的愿意？",
        subtitle_timings=[(matched_text, 0.0, 2.5)],
        duration_sec=140.0,
        semantic_packaging_plan=_semantic_packaging_plan(matched_text),
    )
    metadata = package.to_metadata()

    assert metadata["schema"] == CAPTION_PACKAGE_SCHEMA
    assert metadata["subtitle_event_count"] == 1
    assert metadata["subtitle_text_coverage"] == 1.0
    assert metadata["subtitle_style_profile"] == "jianying_reference_v2"
    assert metadata["packaging_framework"] == HYPERFRAMES_ENGINE
    assert metadata["hyperframes_enabled"] is True
    assert metadata["hyperframes_plan_schema"] == HYPERFRAMES_PLAN_SCHEMA
    assert metadata["hyperframes_element_count"] >= metadata["subtitle_event_count"] + metadata["packaging_event_count"]
    assert metadata["hyperframes_effect_count"] >= metadata["motion_effect_count"]
    assert set(metadata["hyperframes_plan"]["tracks"]) >= {"subtitles", "theme_banners", "keyword_stickers", "impact_words", "watermark"}
    assert metadata["max_subtitle_lines_per_event"] <= 2
    assert metadata["max_subtitle_line_chars"] <= 17
    assert metadata["theme_banner_count"] == 3
    assert metadata["keyword_sticker_count"] == 3
    assert metadata["watermark_event_count"] == 1
    assert metadata["emphasis_keyword_count"] >= 1
    assert metadata["motion_effect_count"] >= 12
    assert metadata["animated_subtitle_event_count"] == 1
    assert metadata["animated_packaging_event_count"] >= 8
    assert metadata["audio_cue_count"] >= 12
    assert metadata["semantic_packaging_source"] == "llm_script_packaging"


def test_caption_package_can_use_creator_bound_children_storybook_style() -> None:
    matched_text = "孩子说好吧，不一定是真的愿意。"
    package = build_caption_package(
        episode=1,
        title="跳舞模式",
        question="孩子说好吧是不是真的愿意？",
        subtitle_timings=[(matched_text, 0.0, 2.5)],
        duration_sec=140.0,
        subtitle_style_profile="children_storybook_v1",
        semantic_packaging_plan=_semantic_packaging_plan(matched_text),
    )
    metadata = package.to_metadata()

    assert metadata["subtitle_style_profile"] == "children_storybook_v1"
    assert "Microsoft YaHei UI,68" in package.ass_text
    assert r"\c&H004AE8FF&\3c&H00B55724&" in package.ass_text
    assert metadata["semantic_packaging_llm_reviewed"] is True
    assert any(item["kind"] == "keyword_pop" for item in metadata["audio_cues"])
    assert any(item["kind"] == "impact_hit" for item in metadata["audio_cues"])
    assert "Style: BlueBanner" in package.ass_text
    assert "Style: BubbleText" in package.ass_text
    assert "Style: ImpactWord" in package.ass_text
    assert "珍妮斯育儿" in package.ass_text
    assert "不想要" not in package.ass_text


def test_caption_package_keeps_theme_title_inside_blue_banner_motion_box() -> None:
    matched_text = "愿望可以被看见，也需要规则帮忙。"
    package = build_caption_package(
        episode=2,
        title="仓储超市",
        question="孩子想要很多东西就是贪心吗？",
        subtitle_timings=[(matched_text, 0.0, 2.5)],
        duration_sec=140.0,
        semantic_packaging_plan=_semantic_packaging_plan(matched_text),
    )

    assert r"\p1\move(760,144,960,144,0,260)" in package.ass_text
    assert r"\move(430,92,610,92,0,240)" in package.ass_text
    assert "m -560 -58 l 560 -58" in package.ass_text


def test_caption_package_keeps_boundary_duration_dense_enough_for_quality_gate() -> None:
    matched_text = "孩子不是黏人，他是在邀请你进入他的世界。"
    package = build_caption_package(
        episode=9,
        title="宾果",
        question="孩子总要你陪玩，是真的黏人吗？",
        subtitle_timings=[(matched_text, 0.0, 3.0)] * 20,
        duration_sec=120.5,
        semantic_packaging_plan=_semantic_packaging_plan(matched_text),
    )

    metadata = package.to_metadata()

    assert metadata["packaging_event_count"] >= 15
    assert metadata["subtitle_event_count"] + metadata["packaging_event_count"] >= 35
    assert metadata["hyperframes_element_count"] >= metadata["subtitle_event_count"] + metadata["packaging_event_count"]
    assert metadata["hyperframes_effect_count"] >= metadata["motion_effect_count"]


def test_caption_package_marks_original_audio_bridge_visibly() -> None:
    matched_text = "听听宾果这一句，她其实没有真的愿意。"
    package = build_caption_package(
        episode=1,
        title="跳舞模式",
        question="孩子说好吧是不是真的愿意？",
        subtitle_timings=[(matched_text, 0.0, 2.5)],
        duration_sec=18.0,
        semantic_packaging_plan=_semantic_packaging_plan(matched_text),
        original_audio_insertions=[
            {
                "insert_at_sec": 4.0,
                "duration_sec": 2.4,
                "matched_text": "听听宾果这一句",
            }
        ],
    )
    metadata = package.to_metadata()

    assert metadata["source_bridge_count"] == 1
    assert any(item["kind"] == "source_bridge" for item in metadata["audio_cues"])
    assert "Style: SourceBridge" in package.ass_text
    assert "原片片段" in package.ass_text
    assert "source_audio_bridges" in set(metadata["hyperframes_plan"]["tracks"])


def test_review_frame_manifest_records_crop_evidence() -> None:
    timestamps = review_frame_timestamps(130.0, min_count=5)
    payload = build_review_frames_manifest(
        episode=1,
        title="跳舞模式",
        video_path="final.mp4",
        review_dir="review_frames",
        frame_paths=[f"review_frames/frame_{index}.jpg" for index in range(5)],
        timestamps_sec=timestamps,
        crop_evidence={"source_clean_crop_filter": "crop=1440:810:180:50"},
    )

    assert payload["schema"] == REVIEW_FRAMES_SCHEMA
    assert payload["frame_count"] == 5
    assert payload["frames"][0]["timestamp_sec"] > 0
    assert payload["crop_evidence"]["source_clean_crop_filter"] == "crop=1440:810:180:50"


def test_clip_entries_keep_evidence_fields_when_duration_or_segment_is_missing() -> None:
    clips = build_clip_entries(
        episode=3,
        clip_starts=[22.0],
        clip_durations=[],
        segment_paths=[],
        scene_spans=[],
    )

    assert clips == [
        {
            "clip_id": "s02e03_clip_01",
            "source_start_sec": 22.0,
            "source_end_sec": 22.0,
            "duration_sec": 0.0,
            "segment_path": None,
            "selection_basis": "source_asr_topic_anchor_with_min_gap",
            "scene_match": {
                "scene_start_sec": 22.0,
                "scene_end_sec": 22.0,
                "snap_delta_sec": 0.0,
                "match_type": "no_scene_index",
            },
        }
    ]


def test_tts_asr_alignment_gate_rejects_missing_timestamps_even_with_text_match() -> None:
    result = evaluate_tts_asr_alignment(
        canonical_text="孩子可以说不。",
        recognized_text="孩子可以说不。",
        tokens=[],
    )

    assert result.status == "fail"
    assert any(issue.code == "tts_asr_no_timestamps" for issue in result.issues)


def test_tts_asr_alignment_gate_warns_for_mid_coverage() -> None:
    tokens = [AsrToken("孩子可以", 0.0, 1.0)]
    result = evaluate_tts_asr_alignment(
        canonical_text="孩子可以说不也可以表达感受",
        recognized_text="孩子可以说不表达",
        tokens=tokens,
        min_pass_coverage=0.9,
        min_warn_coverage=0.45,
    )

    assert result.status == "warn"
    assert any(issue.code == "tts_asr_coverage_warn" for issue in result.issues)


def test_build_asr_aligned_subtitle_timings_uses_token_time_axis() -> None:
    tokens = [
        AsrToken("孩子可以说不", 0.0, 2.0),
        AsrToken("不是不听话", 2.2, 4.0),
    ]

    timings = build_asr_aligned_subtitle_timings(
        ["孩子可以说不", "不是不听话"],
        tokens,
        duration_sec=5.0,
    )

    assert [item.text for item in timings] == ["孩子可以说不", "不是不听话"]
    assert timings[0].start_sec == 0.0
    assert 1.8 <= timings[0].end_sec <= 2.2
    assert timings[1].start_sec >= timings[0].end_sec
    assert timings[1].end_sec <= 5.0


def test_source_asr_clip_selection_keeps_minimum_gap_between_selected_anchors() -> None:
    anchors = [
        SourceAnchor(start_sec=48.0, end_sec=66.0, score=10.0),
        SourceAnchor(start_sec=52.0, end_sec=70.0, score=9.5),
        SourceAnchor(start_sec=80.0, end_sec=98.0, score=9.0),
        SourceAnchor(start_sec=112.0, end_sec=130.0, score=8.0),
        SourceAnchor(start_sec=144.0, end_sec=162.0, score=7.0),
    ]

    starts = select_source_asr_clip_starts(
        anchors,
        source_duration_sec=220.0,
        clip_count=4,
        clip_duration_sec=15.0,
        min_gap_sec=20.0,
    )

    assert len(starts) == 4
    assert 48.0 in starts
    assert 52.0 not in starts
    assert all(b - a >= 20.0 for a, b in zip(starts, starts[1:]))


def test_llm_original_audio_reference_intent_builds_insert_plan_from_script_position() -> None:
    text = "前面先讲观点。这里我们先听一下原片这段对话。后面继续解释为什么孩子会这样。"

    analysis = script_footage_samples.normalize_original_audio_intent_analysis(
        {
            "source": "llm_script_intent",
            "llm_reviewed": True,
            "decision": "insert_original_audio",
            "confidence": 0.91,
            "reason": "脚本明确要求听原片这段对话。",
            "source_quote_requests": [
                {
                    "matched_text": "先听一下原片这段对话",
                    "context": "这里我们先听一下原片这段对话。后面继续解释",
                    "char_start": 9,
                    "char_end": 21,
                    "suggested_duration_sec": 3.2,
                    "reason": "明确要求播放原片对话声音。",
                }
            ],
        },
        script_text=text,
    )
    intents = analysis["source_quote_requests"]
    plan = script_footage_samples.build_original_audio_insert_plan(
        intents=intents,
        selected_source_starts=[42.0],
        narration_duration_sec=100.0,
        source_duration_sec=200.0,
        script_char_count=len(text),
    )

    assert analysis["decision"] == "insert_original_audio"
    assert len(intents) == 1
    assert len(plan) == 1
    assert plan[0]["reason"] == "llm_script_original_footage_context_bridge"
    assert 15.0 <= plan[0]["insert_at_sec"] <= 70.0
    assert plan[0]["source_start_sec"] == 43.0
    assert plan[0]["duration_sec"] == 6.0


def test_llm_original_audio_reference_intent_accepts_quoted_source_dialogue_evidence() -> None:
    text = "前面先讲观点。" + "这里继续铺垫孩子为什么会退让。" * 4 + "宾果最后又说了一句：好吧。你看，这就是很多孩子最容易被大人误会的地方。后面继续解释。"

    analysis = script_footage_samples.normalize_original_audio_intent_analysis(
        {
            "source": "llm_script_intent",
            "llm_reviewed": True,
            "decision": "insert_original_audio",
            "confidence": 0.88,
            "reason": "文案引用原片角色台词作为核心证据，适合插入短原声。",
            "source_quote_requests": [
                {
                    "matched_text": "宾果最后又说了一句：好吧",
                    "context": "宾果最后又说了一句：好吧。你看，这就是很多孩子最容易被大人误会的地方。",
                    "char_start": 7,
                    "char_end": 20,
                    "suggested_duration_sec": 2.4,
                    "reason": "角色台词是后续育儿解读的原片证据。",
                }
            ],
        },
        script_text=text,
    )
    plan = script_footage_samples.build_original_audio_insert_plan(
        intents=analysis["source_quote_requests"],
        selected_source_starts=[10.0, 40.0, 90.0],
        narration_duration_sec=120.0,
        source_duration_sec=150.0,
        script_char_count=len(text),
    )

    assert analysis["decision"] == "insert_original_audio"
    assert len(plan) == 1
    assert plan[0]["source_start_sec"] == 41.0
    assert plan[0]["duration_sec"] == 6.0


def test_llm_original_audio_reference_intent_accepts_scene_evidence_bridges() -> None:
    text = (
        "这一集一开始，孩子们在客厅轮流启动跳舞模式。"
        "布鲁伊想用一次，宾果说好吧。爸爸也想用一次，宾果又让了。"
        "这里不是一句台词的问题，而是孩子一次次把自己的机会让出去。"
    )

    analysis = script_footage_samples.normalize_original_audio_intent_analysis(
        {
            "source": "llm_script_intent",
            "llm_reviewed": True,
            "decision": "insert_original_audio",
            "confidence": 0.9,
            "reason": "文案前半段描述了连续原片场景，适合插入完整情景桥。",
            "source_quote_requests": [
                {
                    "request_type": "scene_evidence",
                    "matched_text": "孩子们在客厅轮流启动跳舞模式",
                    "context": "这一集一开始，孩子们在客厅轮流启动跳舞模式。布鲁伊想用一次",
                    "char_start": 7,
                    "char_end": 22,
                    "suggested_duration_sec": 9.5,
                    "reason": "这是前半段具体剧情证据，不只是抽象观点。",
                },
                {
                    "request_type": "plot_evidence",
                    "matched_text": "宾果又让了",
                    "context": "爸爸也想用一次，宾果又让了。",
                    "char_start": 35,
                    "char_end": 40,
                    "suggested_duration_sec": 8.0,
                    "reason": "连续让步是后续育儿观点的剧情证据。",
                },
            ],
        },
        script_text=text,
    )

    assert analysis["decision"] == "insert_original_audio"
    assert [item["request_type"] for item in analysis["source_quote_requests"]] == ["scene_evidence", "plot_evidence"]
    assert [item["suggested_duration_sec"] for item in analysis["source_quote_requests"]] == [9.5, 8.0]


def test_original_audio_insertions_align_to_tts_asr_subtitle_boundaries_from_script_text() -> None:
    script_text = "Intro point. scene bridge cue. Continue explanation."
    matched = "scene bridge cue"
    insertions = [
        {
            "index": 1,
            "matched_text": matched,
            "char_start": script_text.find(matched),
            "char_end": script_text.find(matched) + len(matched),
            "insert_at_sec": 50.0,
            "duration_sec": 8.0,
        }
    ]
    timings = [
        script_footage_samples.RemixSubtitleTiming(text="Intro point.", start_sec=0.0, end_sec=2.0),
        script_footage_samples.RemixSubtitleTiming(text="scene bridge cue.", start_sec=2.1, end_sec=7.4),
        script_footage_samples.RemixSubtitleTiming(text="Continue explanation.", start_sec=7.5, end_sec=11.0),
    ]

    aligned = script_footage_samples.align_original_audio_insertions_to_tts_asr_timings(
        script_text=script_text,
        insertions=insertions,
        subtitle_timings=timings,
    )

    assert aligned[0]["insert_at_sec"] == 7.48
    assert aligned[0]["insert_tts_asr_alignment_source"] == "matched_script_text_to_tts_asr_subtitle"
    assert aligned[0]["insert_tts_asr_matched_subtitle"] == "scene bridge cue."


def test_original_audio_insertions_are_sorted_after_tts_asr_alignment_not_before() -> None:
    script_text = "early source scene. middle explanation. late source scene."
    insertions = [
        {
            "index": 2,
            "matched_text": "late source scene",
            "char_start": script_text.find("late source scene"),
            "char_end": script_text.find("late source scene") + len("late source scene"),
            "insert_at_sec": 20.0,
            "duration_sec": 6.0,
        },
        {
            "index": 1,
            "matched_text": "early source scene",
            "char_start": script_text.find("early source scene"),
            "char_end": script_text.find("early source scene") + len("early source scene"),
            "insert_at_sec": 50.0,
            "duration_sec": 6.0,
        },
    ]
    timings = [
        script_footage_samples.RemixSubtitleTiming(text="early source scene.", start_sec=1.0, end_sec=4.0),
        script_footage_samples.RemixSubtitleTiming(text="middle explanation.", start_sec=4.2, end_sec=7.0),
        script_footage_samples.RemixSubtitleTiming(text="late source scene.", start_sec=7.2, end_sec=10.0),
    ]

    aligned = script_footage_samples.align_original_audio_insertions_to_tts_asr_timings(
        script_text=script_text,
        insertions=insertions,
        subtitle_timings=timings,
    )

    assert [item["index"] for item in aligned] == [1, 2]
    assert aligned[0]["insert_at_sec"] == 4.08
    assert aligned[1]["insert_at_sec"] == 10.08


def test_llm_original_audio_reference_intent_does_not_trigger_for_visual_reference_only() -> None:
    text = "这一集原片里，孩子把东西摆满了桌子。我们看这里，他其实是在表达愿望。"

    analysis = script_footage_samples.normalize_original_audio_intent_analysis(
        {
            "source": "llm_script_intent",
            "llm_reviewed": True,
            "decision": "insert_original_audio",
            "confidence": 0.52,
            "reason": "只是提到原片画面，没有要求播放声音。",
            "source_quote_requests": [
                {
                    "matched_text": "这一集原片里",
                    "context": "这一集原片里，孩子把东西摆满了桌子",
                    "char_start": 0,
                    "char_end": 7,
                    "suggested_duration_sec": 2.8,
                }
            ],
        },
        script_text=text,
    )

    assert analysis["decision"] == "no_insert"
    assert analysis["source_quote_requests"] == []


def test_original_audio_insertions_shift_subtitles_and_asr_tokens_after_pause() -> None:
    insertions = [{"insert_at_sec": 10.0, "duration_sec": 2.8}]
    timings = [
        SubtitleTiming("插入前", 2.0, 4.0),
        SubtitleTiming("插入后", 12.0, 14.0),
    ]
    tokens = [
        AsrToken("前", 2.0, 2.2),
        AsrToken("后", 12.0, 12.2),
    ]

    shifted_timings = script_footage_samples.shift_subtitle_timings_for_insertions(timings, insertions)
    shifted_tokens = script_footage_samples.shift_asr_tokens_for_insertions(tokens, insertions)

    assert shifted_timings[0].start_sec == 2.0
    assert shifted_timings[1].start_sec == 14.8
    assert shifted_tokens[0].start_sec == 2.0
    assert shifted_tokens[1].start_sec == 14.8


def test_original_audio_insertions_shift_subtitle_that_overlaps_pause_boundary() -> None:
    timings = [SubtitleTiming("提前显示但属于声桥后的字幕", 9.96, 12.0)]
    insertions = [{"insert_at_sec": 10.0, "duration_sec": 3.0}]

    shifted = script_footage_samples.shift_subtitle_timings_for_insertions(timings, insertions)

    assert shifted[0].start_sec == 12.96
    assert shifted[0].end_sec == 15.0


def test_original_audio_insertions_snap_to_subtitle_boundaries() -> None:
    snapped = script_footage_samples.snap_original_audio_insertions_to_subtitle_boundaries(
        [
            {
                "index": 1,
                "insert_at_sec": 10.0,
                "duration_sec": 2.8,
            }
        ],
        subtitle_timings=[
            SubtitleTiming("这一句正在说话", 8.5, 11.2),
            SubtitleTiming("下一句", 11.4, 13.0),
        ],
    )

    assert snapped[0]["insert_at_sec"] == 11.28
    assert snapped[0]["insert_at_original_sec"] == 10.0
    assert snapped[0]["insert_boundary_source"] == "tts_asr_subtitle_boundary"


def test_original_audio_insertions_keep_matched_tts_asr_boundary_before_next_subtitle() -> None:
    snapped = script_footage_samples.snap_original_audio_insertions_to_subtitle_boundaries(
        [
            {
                "index": 1,
                "insert_at_sec": 3.08,
                "duration_sec": 8.0,
                "insert_tts_asr_alignment_source": "matched_script_text_to_tts_asr_subtitle",
                "insert_tts_asr_matched_subtitle_end_sec": 3.0,
            }
        ],
        subtitle_timings=[
            SubtitleTiming("matched cue", 1.0, 3.0),
            SubtitleTiming("next cue", 3.04, 6.0),
        ],
    )

    assert snapped[0]["insert_at_sec"] == 3.08
    assert snapped[0]["insert_boundary_reason"] == "after_matched_tts_asr_subtitle"


def test_original_audio_bridge_boundaries_add_context_without_exceeding_source() -> None:
    refined = script_footage_samples.refine_original_audio_bridge_boundaries(
        [{"source_start_sec": 10.0, "duration_sec": 8.0}],
        source_duration_sec=20.0,
    )

    assert refined[0]["source_start_sec"] == 9.4
    assert refined[0]["duration_sec"] == 10.6
    assert refined[0]["boundary_refinement_source"] == "source_bridge_context_preroll_postroll"


def test_original_audio_insertions_filter_low_confidence_source_mapping() -> None:
    filtered = script_footage_samples.filter_original_audio_insertions_by_mapping_quality(
        [
            {"index": 1, "source_mapping_llm_reviewed": True, "source_mapping_confidence": 0.82},
            {"index": 2, "source_mapping_llm_reviewed": False, "source_mapping_confidence": 0.92},
            {"index": 3, "source_mapping_llm_reviewed": True, "source_mapping_confidence": 0.42},
        ],
        min_confidence=0.6,
    )

    assert [item["index"] for item in filtered] == [1]


def test_bluey_video_segments_use_animation_preserving_encode_settings(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        commands.append(command)

    monkeypatch.setattr(script_footage_samples, "run", fake_run)

    script_footage_samples.build_video_segments(
        Path("source.mp4"),
        tmp_path,
        source_duration=120.0,
        clip_count=1,
        clip_duration=8.0,
        episode=1,
        clip_anchor_starts=[20.0],
        force=True,
    )

    command = commands[0]
    assert command[command.index("-preset") + 1] == script_footage_samples.REMIX_SEGMENT_X264_PRESET
    assert command[command.index("-crf") + 1] == script_footage_samples.REMIX_SEGMENT_X264_CRF
    assert command[command.index("-tune") + 1] == script_footage_samples.REMIX_X264_TUNE
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_bluey_final_mux_uses_animation_preserving_encode_settings(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        commands.append(command)

    monkeypatch.setattr(script_footage_samples, "run", fake_run)

    script_footage_samples.mux_final(
        tmp_path / "montage.mp4",
        tmp_path / "audio.wav",
        tmp_path / "subtitle.ass",
        tmp_path / "final.mp4",
        duration=12.0,
        force=True,
    )

    command = commands[0]
    assert command[command.index("-preset") + 1] == script_footage_samples.REMIX_FINAL_X264_PRESET
    assert command[command.index("-crf") + 1] == script_footage_samples.REMIX_FINAL_X264_CRF
    assert command[command.index("-tune") + 1] == script_footage_samples.REMIX_X264_TUNE
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_original_audio_visual_bridges_replace_montage_with_source_windows(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        commands.append(command)

    monkeypatch.setattr(script_footage_samples, "run", fake_run)

    count = script_footage_samples.apply_original_audio_visual_bridges(
        montage_path=Path("montage.mp4"),
        source_video=Path("source.mp4"),
        output_path=tmp_path / "bridged.mp4",
        insertions=[
            {
                "insert_at_sec": 10.0,
                "source_start_sec": 158.0,
                "duration_sec": 3.0,
            }
        ],
        work_dir=tmp_path / "bridges",
        duration_sec=30.0,
        force=True,
    )

    assert count == 1
    source_commands = [command for command in commands if "source.mp4" in command]
    assert source_commands
    source_command = source_commands[0]
    assert "-ss" in source_command
    assert source_command[source_command.index("-ss") + 1] == "158.000"
    assert any("crop=1440:810:180:50" in part for part in source_command)
    assert source_command[source_command.index("-preset") + 1] == script_footage_samples.REMIX_SEGMENT_X264_PRESET
    assert source_command[source_command.index("-crf") + 1] == script_footage_samples.REMIX_SEGMENT_X264_CRF
    assert any(command[:4] == ["ffmpeg", "-y", "-f", "concat"] for command in commands)


def test_source_asr_index_gate_fails_when_too_few_usable_anchors() -> None:
    result = evaluate_source_asr_index(
        [
            SourceAnchor(start_sec=10.0, end_sec=20.0, status="done"),
            SourceAnchor(start_sec=30.0, end_sec=30.0, status="done"),
            SourceAnchor(start_sec=40.0, end_sec=50.0, status="failed"),
        ],
        min_candidate_count=10,
        min_usable_count=3,
    )

    assert result.status == "fail"
    assert any(issue.code == "source_asr_usable_anchor_count_low" for issue in result.issues)
    assert any(issue.code == "source_asr_candidate_count_low" for issue in result.issues)


def test_episode_report_gate_passes_current_remix_contract_shape() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            **_original_audio_no_insert_report_fields(),
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_style_profile": "children_storybook_v1",
            **_hyperframes_report_fields(),
            "max_subtitle_lines_per_event": 2,
            "max_subtitle_line_chars": 17,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "packaging_event_count": 14,
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "emphasis_keyword_count": 3,
            "motion_effect_count": 16,
            "animated_subtitle_event_count": 10,
            "animated_packaging_event_count": 8,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "pass"


def test_episode_report_gate_warns_but_does_not_fail_when_full_script_exceeds_target_duration() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 242.0,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            **_original_audio_no_insert_report_fields(),
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_style_profile": "children_storybook_v1",
            **_hyperframes_report_fields(),
            "max_subtitle_lines_per_event": 2,
            "max_subtitle_line_chars": 17,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "packaging_event_count": 14,
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "emphasis_keyword_count": 3,
            "motion_effect_count": 16,
            "animated_subtitle_event_count": 10,
            "animated_packaging_event_count": 8,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "warn"
    assert result.passed is True
    assert any(issue.code == "remix_output_duration_out_of_range" for issue in result.issues)


def test_episode_report_gate_rejects_incomplete_visible_subtitle_text() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 0.96,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "packaging_event_count": 14,
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_subtitle_text_incomplete" for issue in result.issues)


def test_episode_report_gate_rejects_subtitle_asr_timing_drift() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_timing_alignment_status": "fail",
            "subtitle_timing_unmatched_count": 1,
            "subtitle_timing_bad_drift_count": 3,
            "subtitle_timing_max_abs_start_drift_sec": 2.0,
            "subtitle_timing_max_abs_end_drift_sec": 2.5,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "packaging_event_count": 14,
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_subtitle_timing_asr_audit_failed" for issue in result.issues)


def test_episode_report_gate_rejects_basic_caption_packaging_without_motion_metrics() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_style_profile": "basic_ass",
            "max_subtitle_lines_per_event": 3,
            "max_subtitle_line_chars": 24,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "packaging_event_count": 6,
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "emphasis_keyword_count": 0,
            "motion_effect_count": 0,
            "animated_subtitle_event_count": 0,
            "animated_packaging_event_count": 0,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_caption_style_profile_invalid" for issue in result.issues)
    assert any(issue.code == "remix_subtitle_lines_out_of_bounds" for issue in result.issues)
    assert any(issue.code == "remix_caption_motion_effects_low" for issue in result.issues)


def test_episode_report_gate_rejects_original_audio_reference_without_insert() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_reference_intent_count": 1,
            "original_audio_insert_count": 0,
            "original_audio_insert_total_duration_sec": 0.0,
            "original_audio_insertions_path": "",
            "original_audio_source_mapping_path": "",
            "original_audio_source_mapping_source": "",
            "original_audio_source_mapping_llm_reviewed": False,
            "original_audio_visual_bridge_count": 0,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_reference_missing" for issue in result.issues)


def test_episode_report_gate_rejects_unreviewed_original_audio_intent_no_insert() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_intent_source": "llm_script_intent",
            "original_audio_intent_decision": "no_insert",
            "original_audio_intent_llm_reviewed": False,
            "original_audio_reference_intent_count": 0,
            "original_audio_insert_count": 0,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_intent_not_reviewed" for issue in result.issues)


def test_episode_report_gate_rejects_non_llm_semantic_caption_packaging() -> None:
    report = _passing_report(1)
    report.update(
        {
            "semantic_packaging_source": "deterministic_fallback",
            "semantic_packaging_llm_reviewed": False,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_semantic_packaging_not_llm_reviewed" for issue in result.issues)


def test_episode_report_gate_rejects_original_audio_bridge_without_visible_overlay() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_reference_intent_count": 1,
            "original_audio_insert_count": 1,
            "original_audio_insert_total_duration_sec": 2.8,
            "original_audio_insertions_path": "original_audio_insertions.json",
            "original_audio_source_mapping_path": "source_mapping.json",
            "original_audio_source_mapping_source": "llm_source_asr_mapping",
            "original_audio_source_mapping_llm_reviewed": True,
            "original_audio_visual_bridge_count": 1,
            "source_bridge_count": 0,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_bridge_visual_missing" for issue in result.issues)


def test_episode_report_gate_rejects_unreviewed_original_audio_source_mapping() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_reference_intent_count": 1,
            "original_audio_insert_count": 1,
            "original_audio_insert_total_duration_sec": 2.8,
            "original_audio_insertions_path": "original_audio_insertions.json",
            "original_audio_source_mapping_path": "source_mapping.json",
            "original_audio_source_mapping_source": "source_asr_mapping_fallback",
            "original_audio_source_mapping_llm_reviewed": False,
            "original_audio_visual_bridge_count": 1,
            "source_bridge_count": 1,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_source_mapping_not_reviewed" for issue in result.issues)


def test_episode_report_gate_rejects_original_audio_without_video_bridge() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_reference_intent_count": 1,
            "original_audio_insert_count": 1,
            "original_audio_insert_total_duration_sec": 2.8,
            "original_audio_insertions_path": "original_audio_insertions.json",
            "original_audio_source_mapping_path": "source_mapping.json",
            "original_audio_source_mapping_source": "llm_source_asr_mapping",
            "original_audio_source_mapping_llm_reviewed": True,
            "original_audio_visual_bridge_count": 0,
            "source_bridge_count": 1,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_visual_bridge_missing" for issue in result.issues)


def test_episode_report_gate_rejects_original_audio_bridge_that_is_too_short() -> None:
    report = _passing_report(1)
    report.update(
        {
            "original_audio_reference_intent_count": 1,
            "original_audio_insert_count": 1,
            "original_audio_insert_total_duration_sec": 2.8,
            "original_audio_insertions_path": "original_audio_insertions.json",
            "original_audio_source_mapping_path": "source_mapping.json",
            "original_audio_source_mapping_source": "llm_source_asr_mapping",
            "original_audio_source_mapping_llm_reviewed": True,
            "original_audio_visual_bridge_count": 1,
            "source_bridge_count": 1,
        }
    )

    result = evaluate_episode_report(report)

    assert result.status == "fail"
    assert any(issue.code == "remix_original_audio_bridge_too_short" for issue in result.issues)


def test_episode_report_gate_rejects_moss_only_subtitle_alignment() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": "moss_tts_live_segments",
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_subtitle_alignment_source_invalid" for issue in result.issues)


def test_episode_report_gate_warns_on_scene_index_fallback() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            **_original_audio_no_insert_report_fields(),
            "scene_index_path": "scene_index.json",
            "scene_index_status": "fallback_single_scene",
            "scene_count": 1,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_style_profile": "children_storybook_v1",
            **_hyperframes_report_fields(),
            "max_subtitle_lines_per_event": 2,
            "max_subtitle_line_chars": 17,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "emphasis_keyword_count": 3,
            "motion_effect_count": 16,
            "animated_subtitle_event_count": 10,
            "animated_packaging_event_count": 8,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "warn"
    assert any(issue.code == "remix_scene_index_fallback" for issue in result.issues)


def test_episode_report_gate_rejects_missing_caption_packaging_evidence() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "theme_banner_count": 2,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "review_frames_manifest_path": "review_frames.json",
            "review_frame_count": 5,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_caption_package_missing" for issue in result.issues)
    assert any(issue.code == "remix_theme_banner_count_low" for issue in result.issues)


def test_episode_report_gate_rejects_missing_review_frames() -> None:
    result = evaluate_episode_report(
        {
            "output_path": "final.mp4",
            "narration_path": "narration.wav",
            **_tts_voice_report_fields(),
            "subtitle_path": "subtitle.ass",
            "caption_package_path": "caption_package.json",
            "output_duration_sec": 136.66,
            "subtitle_alignment_source": TTS_ALIGNMENT_SOURCE,
            "tts_asr_status": "done",
            "tts_asr_coverage": 0.9964,
            "source_asr_status": "done",
            "source_asr_anchor_count": 14,
            "scene_index_path": "scene_index.json",
            "scene_index_status": "detected",
            "scene_count": 24,
            "subtitle_event_count": 42,
            "subtitle_text_coverage": 1.0,
            "subtitle_timing_alignment_status": "pass",
            "subtitle_timing_unmatched_count": 0,
            "subtitle_timing_bad_drift_count": 0,
            "subtitle_timing_max_abs_start_drift_sec": 0.04,
            "subtitle_timing_max_abs_end_drift_sec": 0.12,
            "subtitle_timing_audit_path": "subtitle_timing_audit.json",
            "theme_banner_count": 3,
            "keyword_sticker_count": 3,
            "watermark_event_count": 1,
            "review_frames_manifest_path": "",
            "review_frame_count": 0,
        }
    )

    assert result.status == "fail"
    assert any(issue.code == "remix_review_frames_missing" for issue in result.issues)


def test_scene_index_normalization_filters_short_and_clamps_bounds() -> None:
    scenes = normalize_scene_spans(
        [
            SceneSpan(start_sec=-1.0, end_sec=4.0, score=1.0),
            SceneSpan(start_sec=4.1, end_sec=4.2, score=2.0),
            SceneSpan(start_sec=5.0, end_sec=12.0, score=3.0),
            SceneSpan(start_sec=11.0, end_sec=30.0, score=4.0),
        ],
        source_duration_sec=20.0,
        min_duration_sec=0.5,
    )

    assert [(item.start_sec, item.end_sec) for item in scenes] == [(0.0, 4.0), (5.0, 12.0), (12.0, 20.0)]


def test_scene_index_matches_clip_to_containing_scene() -> None:
    match = match_clip_to_scene(
        clip_start_sec=12.5,
        clip_duration_sec=5.0,
        scenes=[
            SceneSpan(start_sec=0.0, end_sec=10.0),
            SceneSpan(start_sec=10.0, end_sec=20.0),
        ],
    )

    assert match["match_type"] == "contains_start"
    assert match["scene_start_sec"] == 10.0
    assert match["scene_end_sec"] == 20.0


def test_scene_index_payload_records_fallback_single_scene() -> None:
    payload = build_scene_index_payload(
        video_path=__file__,
        source_duration_sec=42.0,
        status="fallback_single_scene",
        scenes=[SceneSpan(start_sec=0.0, end_sec=42.0, source="fallback")],
        threshold=30.0,
        frame_skip=2,
        max_runtime_sec=180.0,
    )

    assert payload["schema"] == "roughcut.remix.scene_index.v1"
    assert payload["status"] == "fallback_single_scene"
    assert payload["scene_count"] == 1


def test_scene_index_uses_ffmpeg_scene_fallback_when_pyscenedetect_is_unavailable(monkeypatch) -> None:
    def fake_detect_scenes(*_args, **_kwargs):
        return []

    class FakeCompleted:
        returncode = 0
        stderr = "showinfo pts_time:4.000 other\nshowinfo pts_time:8.500 other\n"

    def fake_run(*_args, **_kwargs):
        return FakeCompleted()

    monkeypatch.setattr(remix_scene_index, "detect_scenes", fake_detect_scenes)
    monkeypatch.setattr(remix_scene_index.subprocess, "run", fake_run)

    status, scenes = remix_scene_index.detect_scene_spans(
        Path("source.mp4"),
        source_duration_sec=12.0,
    )

    assert status == "detected"
    assert [scene.source for scene in scenes] == ["ffmpeg_scene", "ffmpeg_scene", "ffmpeg_scene"]
    assert [(scene.start_sec, scene.end_sec) for scene in scenes] == [(0.0, 4.0), (4.0, 8.5), (8.5, 12.0)]


