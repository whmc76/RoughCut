from types import SimpleNamespace

from roughcut.api.jobs import (
    _attach_content_profile_capability_orchestration,
    _ensure_content_understanding_payload,
    _smart_cut_rule_reasons_from_capabilities,
)
from roughcut.review.content_profile import _attach_content_understanding_timed_focus_spans, assess_content_profile_automation
from roughcut.review.downstream_context import (
    build_downstream_context,
    resolve_downstream_profile,
    strip_publication_only_profile_fields,
)


def test_smart_cut_rules_follow_speech_density_capability() -> None:
    assert _smart_cut_rule_reasons_from_capabilities(["filler_word"], ["speech_density_trim"]) == [
        "filler_word",
        "repeated_speech",
        "silence",
        "low_signal_subtitle",
    ]
    assert _smart_cut_rule_reasons_from_capabilities(
        ["filler_word", "silence", "pause", "low_signal_subtitle"],
        ["chapter_cards"],
    ) == []


def test_attach_content_understanding_timed_focus_spans_from_evidence_bundle() -> None:
    profile = {
        "content_understanding": {
            "video_type": "unboxing",
            "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
        }
    }
    evidence_bundle = {
        "semantic_fact_inputs": {
            "timed_focus_spans": [
                {
                    "timestamp": "00:00-00:02",
                    "text": "开场先讲结论",
                    "type": "hook",
                    "start_time": 0.0,
                    "end_time": 2.0,
                },
                {
                    "timestamp": "00:02-00:05",
                    "text": "这里拿 EDC17 和 EDC37 做对比",
                    "type": "comparison",
                    "start_time": 2.0,
                    "end_time": 5.0,
                },
            ]
        }
    }

    enriched = _attach_content_understanding_timed_focus_spans(profile, evidence_bundle=evidence_bundle)

    assert len(enriched["content_understanding"]["timed_focus_spans"]) == 2
    assert enriched["content_understanding"]["timed_focus_spans"][0]["type"] == "hook"


def test_downstream_context_strips_publication_only_profile_fields() -> None:
    context = build_downstream_context(
        {
            "subject_brand": "MAXACE",
            "subject_model": "蜂巢3",
            "cover_title": {"main": "MAXACE蜂巢3顶配开箱"},
            "cover_style": "battle",
            "cover_style_label": "战斗风",
            "cover_variant_count": 3,
            "resolved_review_user_feedback": {
                "summary": "展示蜂巢3顶配细节",
                "cover_title": "不应进入编辑上下文",
            },
        }
    )

    resolved_profile = context["resolved_profile"]
    assert resolved_profile["subject_brand"] == "MAXACE"
    assert resolved_profile["summary"] == "展示蜂巢3顶配细节"
    assert "cover_title" not in resolved_profile
    assert "cover_style" not in resolved_profile
    assert "cover_style_label" not in resolved_profile
    assert "cover_variant_count" not in resolved_profile
    assert "cover_title" not in resolve_downstream_profile(context)


def test_edit_profile_automation_does_not_score_or_request_cover_fields() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "edc_tactical",
            "subject_type": "EDC折刀",
            "video_theme": "MAXACE 蜂巢3顶配结构展示",
            "summary": "这条视频围绕 MAXACE 蜂巢3顶配展开，介绍开箱、结构细节和上手体验。",
            "hook_line": "先看这把蜂巢3顶配的锁定细节",
            "cover_title": {"main": "不应参与编辑画像评分"},
            "engagement_question": "你更关注这类折刀的结构还是手感？",
            "search_queries": ["MAXACE 蜂巢3", "蜂巢3 顶配"],
            "subject_brand": "MAXACE",
            "subject_model": "蜂巢3顶配",
            "source_context": {"video_description": "任务创建时已填写视频说明。"},
        },
        subtitle_items=[{"text_final": "这是一段关于蜂巢三顶配结构和手感的字幕。"} for _ in range(8)],
        source_name="maxace 蜂巢3 顶配.MOV",
        auto_confirm_enabled=True,
        threshold=0.9,
    )

    combined = " ".join(list(automation["reasons"]) + list(automation["review_reasons"]))
    assert "封面" not in combined
    assert "剪辑钩子可用" in automation["reasons"]


def test_strip_publication_fields_removes_cover_from_final_profile_payload() -> None:
    final_profile = strip_publication_only_profile_fields(
        {
            "summary": "展示蜂巢3顶配细节",
            "cover_title": {"main": "不应写入 content_profile_final"},
            "cover_variant_count": 5,
            "resolved_review_user_feedback": {
                "cover_title": "不应保留",
                "summary": "人工确认后的摘要",
            },
        }
    )

    assert "cover_title" not in final_profile
    assert "cover_variant_count" not in final_profile
    assert final_profile["resolved_review_user_feedback"] == {"summary": "人工确认后的摘要"}


def test_ensure_content_understanding_payload_preserves_timed_focus_spans() -> None:
    payload = _ensure_content_understanding_payload(
        {
            "subject_type": "NITECORE EDC17 手电",
            "content_understanding": {
                "video_type": "unboxing",
                "content_domain": "flashlight",
                "primary_subject": "NITECORE EDC17 手电",
                "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
                "timed_focus_spans": [
                    {
                        "timestamp": "00:00-00:02",
                        "text": "开场先讲结论",
                        "type": "hook",
                        "start_time": 0.0,
                        "end_time": 2.0,
                    }
                ],
                "needs_review": False,
            },
        }
    )

    assert payload is not None
    assert payload["content_understanding"]["timed_focus_spans"][0]["timestamp"] == "00:00-00:02"
    assert payload["content_understanding"]["evidence_spans"][0]["type"] == "comparison"


def test_attach_content_profile_capability_orchestration_for_tutorial_preview() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
        job_flow_mode="smart_assist",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a", "insert-b"],
            "music_asset_ids": ["music-a"],
            "intro_asset_id": "intro-a",
            "watermark_asset_id": "wm-a",
        },
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["strategy_type"] == "step_demonstration"
    assert orchestration["job_flow_mode"] == "smart_assist"
    assert orchestration["local_asset_inventory"]["auxiliary_video_count"] == 1
    assert orchestration["local_asset_inventory"]["image_count"] == 2
    assert orchestration["local_asset_inventory"]["audio_count"] == 1
    assert orchestration["capabilities"]["screen_focus"] == "suggest"
    assert orchestration["capabilities"]["local_broll_insert"] == "suggest"
    assert orchestration["capabilities"]["local_audio_cues"] == "suggest"


def test_attach_content_profile_capability_orchestration_keeps_commentary_baseline() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={},
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "subject_type": "观点口播",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["strategy_type"] == "information_density"
    assert orchestration["capabilities"]["speech_density_trim"] == "auto_apply"
    assert orchestration["capabilities"]["screen_focus"] == "disabled"
    assert orchestration["capabilities"]["local_broll_insert"] == "disabled"


def test_attach_content_profile_capability_orchestration_material_usage_main_only_disables_supporting_materials() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a", "insert-b"],
            "music_asset_ids": ["music-a"],
        },
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "product_controls": {
                            "edit_mode": "tutorial",
                            "automation_level": "standard",
                            "material_usage": "main_only",
                        }
                    }
                },
            )
        ],
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["product_controls"]["effective"]["material_usage"] == "main_only"
    assert orchestration["capabilities"]["local_broll_insert"] == "disabled"
    assert orchestration["capabilities"]["local_audio_cues"] == "disabled"
    assert orchestration["capabilities"]["multi_material_assembly"] == "disabled"


def test_attach_content_profile_capability_orchestration_conservative_tutorial_downgrades_focus() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a"],
            "music_asset_ids": ["music-a"],
        },
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "product_controls": {
                            "edit_mode": "tutorial",
                            "automation_level": "conservative",
                            "material_usage": "all_uploaded",
                        }
                    }
                },
            )
        ],
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["product_controls"]["effective"]["automation_level"] == "conservative"
    assert orchestration["capabilities"]["screen_focus"] == "suggest"
    assert orchestration["capabilities"]["local_broll_insert"] == "suggest"


def test_attach_content_profile_capability_orchestration_recommends_multi_material_mode() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a"],
            "music_asset_ids": ["music-a"],
        },
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4", "cut-1.mp4", "cut-2.mp4"],
            "subject_type": "观点口播",
        },
        job=job,
    )

    assert payload is not None
    controls = payload["product_controls"]
    assert controls["requested"]["edit_mode"] == "auto"
    assert controls["recommended"]["edit_mode"] == "multi_material"
    assert payload["capability_orchestration"]["product_controls"]["effective"]["edit_mode"] == "multi_material"


def test_attach_content_profile_capability_orchestration_uses_create_task_rule_and_capability_choices() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={},
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "smart_cut_rules": {
                            "enabled_reasons": ["filler_word"],
                            "fillerEnabled": True,
                            "catchphraseEnabled": False,
                            "repeatedEnabled": False,
                            "pauseEnabled": False,
                            "smartDeleteEnabled": False,
                        },
                        "material_enhancement_modes": ["voice_enhancement"],
                        "capability_overrides": {
                            "screen_focus": "disabled",
                            "chapter_cards": "disabled",
                            "local_broll_insert": "disabled",
                            "local_audio_cues": "disabled",
                            "highlight_window_selection": "disabled",
                            "multi_material_assembly": "disabled",
                        },
                    }
                },
            )
        ],
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "subject_type": "观点口播",
        },
        job=job,
    )

    assert payload is not None
    assert payload["smart_cut_rules"]["enabled_reasons"] == ["filler_word"]
    assert payload["material_enhancement_modes"] == ["voice_enhancement"]
    orchestration = payload["capability_orchestration"]
    assert orchestration["capabilities"]["speech_density_trim"] == "auto_apply"
    assert orchestration["capabilities"]["screen_focus"] == "disabled"
    assert orchestration["capabilities"]["local_audio_cues"] == "disabled"
