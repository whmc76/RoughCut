from __future__ import annotations

import uuid
from types import SimpleNamespace

from roughcut.review.telegram_bot import _build_content_profile_review_message


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
