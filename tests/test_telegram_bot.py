from __future__ import annotations

import uuid
from types import SimpleNamespace

from roughcut.review.telegram_bot import _build_content_profile_review_message, _build_subtitle_review_artifact_lines


def test_build_content_profile_review_message_includes_identity_evidence_bundle():
    message = _build_content_profile_review_message(
        source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
        job_id=uuid.uuid4(),
        review=SimpleNamespace(workflow_mode="standard_edit", enhancement_modes=[]),
        draft={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "开箱与上手评测",
            "summary": "这条视频主要围绕一款EDC机能包展开，具体品牌型号待人工确认。",
            "transcript_excerpt": "[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。",
            "identity_review": {
                "required": True,
                "first_seen_brand": True,
                "first_seen_model": True,
                "conservative_summary": True,
                "support_sources": ["transcript", "source_name"],
                "evidence_strength": "weak",
                "reason": "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_subtitle_snippets": ["[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。"],
                    "matched_glossary_aliases": {"brand": ["鸿福"], "model": ["F叉二一小副包"]},
                    "matched_source_name_terms": ["鸿福", "F叉二一小副包"],
                    "matched_visible_text_terms": ["狐蝠工业"],
                    "matched_evidence_terms": [],
                },
            },
            "automation_review": {
                "score": 0.64,
                "threshold": 0.72,
                "review_reasons": ["首次品牌/型号证据不足，已退化为保守摘要"],
                "blocking_reasons": ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
            },
        },
        packaging_assets={},
        packaging_config={},
    )

    assert "主体证据包：" in message
    assert "- 候选品牌：狐蝠工业" in message
    assert "- 候选型号：FXX1小副包" in message
    assert "- 支撑来源：字幕，文件名" in message
    assert "- 命中词表别名：品牌：鸿福; 型号：F叉二一小副包" in message
    assert "- 文件名命中：鸿福，F叉二一小副包" in message
    assert "[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。" in message


def test_build_content_profile_review_message_includes_compact_ocr_and_transcript_evidence():
    message = _build_content_profile_review_message(
        source_name="demo.mp4",
        job_id=uuid.uuid4(),
        review=SimpleNamespace(workflow_mode="standard_edit", enhancement_modes=[]),
        draft={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "开箱与上手评测",
            "summary": "围绕狐蝠工业 FXX1小副包展开。",
            "ocr_evidence": {
                "source_name": "demo.mp4",
                "frame_count": 3,
                "line_count": 2,
                "status": "ok",
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
                "raw_snippets": [
                    {"text": "狐蝠工业", "frame_index": 0},
                    {"text": "FXX1小副包", "frame_index": 1},
                ],
            },
            "transcript_evidence": {
                "provider": "qwen_asr",
                "model": "qwen3-asr-1.7b",
                "prompt": "优先识别品牌、型号、颜色与规格。",
                "segments": [{"text": "这期开箱狐蝠工业 FXX1小副包。"}],
                "raw_payload": {"large": "payload"},
            },
        },
        packaging_assets={},
        packaging_config={},
    )

    assert "OCR / 转写证据：" in message
    assert "- OCR 文字摘要：狐蝠工业 FXX1小副包 开箱（3 帧，2 行）" in message
    assert "- 转写证据：qwen_asr / qwen3-asr-1.7b" in message
    assert "Prompt 轨迹：优先识别品牌、型号、颜色与规格。" in message
    assert "raw_payload" not in message


def test_build_subtitle_review_artifact_lines_summarizes_patch_consistency_and_quality():
    lines = _build_subtitle_review_artifact_lines(
        {
            "subtitle_term_resolution_patch": {
                "candidate_terms": ["狐蝠工业", "FXX1小副包"],
                "blocking": True,
                "metrics": {
                    "patch_count": 2,
                    "accepted_count": 1,
                    "pending_count": 1,
                    "auto_applied_count": 0,
                },
            },
            "subtitle_consistency_report": {
                "score": 88.2,
                "blocking": True,
                "blocking_reasons": ["字幕与文件名品牌不一致"],
            },
            "subtitle_quality_report": {
                "score": 91.5,
                "blocking": False,
                "warning_reasons": ["短碎句率偏高 1.20%"],
            },
        }
    )

    assert "- 术语修复：2 条候选，已接受 1，待审 1，自动应用 0" in lines
    assert "- 术语候选：狐蝠工业，FXX1小副包" in lines
    assert "- 处理动作：先人工确认 1 条术语候选，再继续后续摘要与成片流程。" in lines
    assert "- 一致性：88.20 分，阻断" in lines
    assert "- 一致性阻断：字幕与文件名品牌不一致" in lines
    assert "- 处理动作：先复核一致性冲突：字幕与文件名品牌不一致；确认后如需自动回退，从 subtitle_consistency_review 起重跑。" in lines
    assert "- 质量：91.50 分，通过" in lines
    assert "- 质量提醒：短碎句率偏高 1.20%" in lines
    assert "- 处理动作：如需消除字幕质量提醒，可从 subtitle_postprocess 起重跑。" in lines
