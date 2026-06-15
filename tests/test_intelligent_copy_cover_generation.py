from __future__ import annotations

import asyncio
import base64
import inspect
import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from roughcut.providers import image_generation as imagegen
from roughcut.api import intelligent_copy as intelligent_copy_api
from roughcut.api.schemas import IntelligentCopyGenerateTaskListOut
from roughcut import cover_title_contract as ctc
from roughcut.intelligent_copy_layout import (
    smart_copy_cover_source_image_path,
    smart_copy_cover_source_manifest_path,
    smart_copy_material_json_path,
    smart_copy_platform_body_path,
    smart_copy_platform_tags_path,
    smart_copy_platform_titles_path,
)
from roughcut.media import output as media_output
from roughcut.providers.image_generation import resolve_image_generation_size
from roughcut import publication_platform_matrix as ppm
from roughcut.review import intelligent_copy as ic
from roughcut.review import platform_copy as pc


@pytest.fixture(autouse=True)
def _disable_real_codex_imagegen_autorun(monkeypatch) -> None:
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "")


def test_intelligent_copy_transcript_helpers_use_canonical_surface() -> None:
    subtitle_items = [
        {
            "text_raw": "那个 EDC 折刀",
            "text_norm": "这是 MAXACE 美杜莎4",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        {
            "text_raw": "看一下细节",
            "text_norm": "看一下细节",
            "text_final": "看一下细节",
        },
    ]
    captured: dict[str, str] = {}

    original_should_use = ic._should_use_intelligent_copy_fast_path
    try:
        ic._should_use_intelligent_copy_fast_path = lambda text: captured.setdefault("text", text) == "__never__"
        ic._build_intelligent_copy_fast_profile(
            video_path=Path("demo.mp4"),
            subtitle_items=subtitle_items,
            copy_style="attention_grabbing",
        )
    finally:
        ic._should_use_intelligent_copy_fast_path = original_should_use

    excerpt = ic.build_transcript_excerpt_for_cover(subtitle_items)

    assert "这是 MAXACE 美杜莎4" in excerpt
    assert "EDC 折刀" not in excerpt
    assert "这是 MAXACE 美杜莎4" in captured["text"]
    assert "EDC 折刀" not in captured["text"]


def test_merge_intelligent_copy_profile_hints_uses_canonical_surface() -> None:
    profile = ic._merge_intelligent_copy_profile_hints(
        content_profile={},
        video_path=Path("MAXACE 美杜莎4.mp4"),
        subtitle_items=[
            {
                "text_raw": "这个 EDC 折刀",
                "text_norm": "这是 MAXACE 美杜莎4 直跳",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        copy_style="attention_grabbing",
    )

    assert profile["hook_line"].startswith("这是 MAXACE 美杜莎4")
    assert profile["subject_type"] == "EDC跳刀"


def test_image_generation_size_uses_closest_supported_orientation() -> None:
    assert resolve_image_generation_size(1280, 720) == "1536x1024"
    assert resolve_image_generation_size(1080, 1920) == "1024x1536"
    assert resolve_image_generation_size(1080, 1440) == "1024x1536"
    assert resolve_image_generation_size(1000, 1000) == "1024x1024"


def test_infer_intelligent_copy_subject_type_prefers_jump_knife_when_explicit() -> None:
    assert ic._infer_intelligent_copy_subject_type("MAXACE 美杜莎4 直跳双版本开箱") == "EDC跳刀"


def test_dreamina_runner_defaults_to_vendored_module() -> None:
    runner = imagegen._resolve_dreamina_runner_script(SimpleNamespace(intelligent_copy_cover_dreamina_runner_script=""))

    assert runner.name == "dreamina_web_cdp.mjs"
    assert runner.exists()


def test_generate_task_schema_accepts_historical_platform_material_without_constraints() -> None:
    payload = {
        "tasks": [
            {
                "id": "task-1",
                "folder_path": r"Z:\material\demo",
                "copy_style": "attention_grabbing",
                "use_existing_cover": False,
                "status": "completed",
                "progress": 100,
                "stage": "completed",
                "message": "done",
                "created_at": "2026-05-28T05:00:00+00:00",
                "updated_at": "2026-05-28T05:10:00+00:00",
                "started_at": "2026-05-28T05:00:00+00:00",
                "completed_at": "2026-05-28T05:10:00+00:00",
                "material_dir": r"Z:\material\demo\smart-copy",
                "error": "",
                "inspection": {
                    "folder_path": r"Z:\material\demo",
                    "material_dir": r"Z:\material\demo\smart-copy",
                    "video_file": None,
                    "subtitle_file": None,
                    "cover_file": None,
                    "warnings": [],
                },
                "result": {
                    "folder_path": r"Z:\material\demo",
                    "material_dir": r"Z:\material\demo\smart-copy",
                    "markdown_path": r"Z:\material\demo\smart-copy\platform-packaging.md",
                    "json_path": r"Z:\material\demo\smart-copy\smart-copy.json",
                    "use_existing_cover": False,
                    "copy_style": "attention_grabbing",
                    "inspection": {
                        "folder_path": r"Z:\material\demo",
                        "material_dir": r"Z:\material\demo\smart-copy",
                        "video_file": None,
                        "subtitle_file": None,
                        "cover_file": None,
                        "warnings": [],
                    },
                    "highlights": {},
                    "content_profile_summary": {},
                    "publish_ready": True,
                    "blocking_reasons": [],
                    "warnings": [],
                    "platforms": [
                        {
                            "key": "xiaohongshu",
                            "label": "小红书",
                            "body_label": "正文",
                            "tag_label": "话题",
                            "titles": ["标题 1", "标题 2", "标题 3"],
                            "primary_title": "标题 1",
                            "body": "正文",
                            "tags": ["#标签"],
                            "tags_copy": "#标签",
                            "full_copy": "完整文案",
                            "cover_path": r"Z:\material\demo\smart-copy\cover.jpg",
                            "publish_ready": True,
                            "blocking_reasons": [],
                        }
                    ],
                },
                "partial_result": None,
            }
        ]
    }

    model = IntelligentCopyGenerateTaskListOut.model_validate(payload)

    assert len(model.tasks) == 1
    assert model.tasks[0].result is not None
    assert model.tasks[0].result.platforms[0].constraints.title_limit == 0


def test_generation_task_is_orphaned_when_same_process_worker_missing_after_grace(monkeypatch) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    task = {
        "id": "task-orphaned",
        "status": "running",
        "worker_owner_pid": 4321,
        "last_heartbeat_at": now.isoformat(),
    }

    monkeypatch.setattr(intelligent_copy_api, "_GENERATION_TASKS", {})
    monkeypatch.setattr(intelligent_copy_api, "_GENERATION_TASK_ORPHAN_GRACE_SECONDS", 45)
    monkeypatch.setattr(intelligent_copy_api.os, "getpid", lambda: 4321)

    assert intelligent_copy_api._generation_task_is_orphaned(task) is False

    task["last_heartbeat_at"] = (now - timedelta(seconds=60)).isoformat()

    assert intelligent_copy_api._generation_task_is_orphaned(task) is True


def test_recover_generation_task_runtime_state_marks_orphaned_task_failed(monkeypatch) -> None:
    task = {
        "id": "task-orphaned",
        "status": "running",
        "stage": "running",
        "worker_owner_pid": 4321,
        "last_heartbeat_at": (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=60)).isoformat(),
    }

    monkeypatch.setattr(intelligent_copy_api, "_load_generation_tasks", lambda: [task])
    monkeypatch.setattr(intelligent_copy_api, "_GENERATION_TASKS", {})
    monkeypatch.setattr(intelligent_copy_api.os, "getpid", lambda: 4321)
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        intelligent_copy_api,
        "_mark_generation_task_failed",
        lambda task_id, error: recorded.append((task_id, error)) or {"id": task_id, "error": error},
    )

    intelligent_copy_api._recover_generation_task_runtime_state()

    assert recorded == [("task-orphaned", "生成任务未找到存活执行器，请重新生成。")]


def test_platform_cover_prompt_for_codex_requires_integrated_full_cover_typography(monkeypatch) -> None:
    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(intelligent_copy_cover_image_backend="codex_builtin"),
    )
    prompt = ic._build_platform_cover_image_prompt(
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
        cover_brief={
            "video_type": "开箱把玩",
            "product_identity": "MOT 风灵音叉推牌",
            "selling_angle": "锆合金质感",
            "visual_brief": "真实手持产品，标题集中醒目。",
            "background_strategy": "replace_background_if_needed",
            "critical_detail_notes": ["镜面反光区域是实心金属高光，不是开孔、镂空或缺口。"],
        },
    )

    assert "平台：抖音" in prompt
    assert "视频题材：开箱把玩" in prompt
    assert "主体说明：保持参考图中的同一商品主体和版本关系" in prompt
    assert "背景策略：背景不是硬约束" in prompt
    assert "基于参考图生成一张可直接发布的完整视频封面" in prompt
    assert "风格：EDC 电影英雄封面" in prompt
    assert "必须直接在最终位图里完整渲染这些真实文字" in prompt
    assert "主标题「" in prompt
    assert "副标题「" in prompt
    assert "只允许渲染上面明确要求的品牌行、主标题、副标题和吸睛文案" in prompt
    assert "硬合同：必须保持参考图产品主体一致，不允许改刀型、结构、开合状态或主角度" in prompt
    assert "标题必须按四层信息布局直接完整渲染：品牌行、主标题行、副标题行、吸睛文案行" in prompt
    assert "主标题行必须最大、最有压场感；副标题行明显更小一档，品牌行独立在上方，吸睛文案行作为底部 badge" in prompt
    assert "标题区和主体区必须明显分离" in prompt
    assert "构图优先做成成熟短视频爆款封面" in prompt
    assert "编辑策略：前景主体结构保留优先" in prompt
    assert "标题字效必须直接在位图里完成，不要留空白牌位等后期占位方案" in prompt
    assert "厚重金属海报字" not in prompt
    assert "镜面反光区域是实心金属高光，不是开孔、镂空或缺口。" in prompt
    assert "背景特效必须保留高能电光、金属质感、火焰能量和赛博发光史诗氛围" in prompt
    assert "标题舞台必须集中在上中部，主体展示集中在下半区或左右下方" in prompt


def test_platform_cover_prompt_for_dreamina_defers_title_rendering(monkeypatch) -> None:
    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(intelligent_copy_cover_image_backend="dreamina_web"),
    )
    prompt = ic._build_platform_cover_image_prompt(
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
        cover_brief={
            "video_type": "开箱把玩",
            "product_identity": "MOT 风灵音叉推牌",
            "selling_angle": "锆合金质感",
            "visual_brief": "真实手持产品，标题集中醒目。",
            "background_strategy": "preserve_reference_background",
            "critical_detail_notes": ["镜面高光是实心金属，不是开孔。"],
        },
    )

    assert "基于参考图生成封面底图" in prompt
    assert "硬合同：" in prompt
    assert "标题由后期统一叠加" in prompt
    assert "不要在图中生成任何文字" in prompt
    assert "前景主体结构保留优先" in prompt
    assert "镜面高光是实心金属，不是开孔。" in prompt
    assert "背景策略：优先保留参考图里已有的背景布置" in prompt


def test_fallback_cover_brief_defaults_to_replace_background_for_highlight_source() -> None:
    brief = ic._build_fallback_cover_brief(
        packaging={"highlights": {"product": "MAXACE 美杜莎4", "video_type": "开箱对比"}},
        content_profile={},
        copy_brief={"topic_subject": "MAXACE 美杜莎4"},
        cover_source_manifest={"source": "video_highlight"},
        existing_cover_path=None,
    )

    assert brief["background_strategy"] == "replace_background_if_needed"
    assert "刀身镜面反光区域是实心金属高光，不是开孔、镂空、雕花或缺口。" in brief["critical_detail_notes"]


def test_fallback_cover_brief_does_not_inject_dual_subject_notes_for_compare_wording() -> None:
    brief = ic._build_fallback_cover_brief(
        packaging={"highlights": {"product": "MAXACE 美杜莎4", "video_type": "开箱对比"}},
        content_profile={"subject_type": "EDC折刀", "summary": "顶配和次顶配双版同框开箱"},
        copy_brief={"topic_subject": "MAXACE 美杜莎4 顶配次顶配", "intent": "comparison"},
        cover_source_manifest={"source": "video_highlight"},
        existing_cover_path=None,
    )

    assert "不要给刀身添加不存在的浮雕、动物纹样、刻字或装饰图案。" in brief["critical_detail_notes"]
    assert "保留螺丝数量、位置、开槽方向、边角切面和金属分区，不要凭空增删五金细节。" in brief["critical_detail_notes"]
    assert not any("两把" in note or "双主体" in note for note in brief["critical_detail_notes"])
    assert brief["product_identity"] == "MAXACE 美杜莎4 顶配vs次顶配"


def test_fallback_cover_brief_preserves_background_for_existing_cover_source(tmp_path) -> None:
    existing_cover = tmp_path / "cover.jpg"
    existing_cover.write_bytes(b"cover")

    brief = ic._build_fallback_cover_brief(
        packaging={"highlights": {"product": "MAXACE 美杜莎4", "video_type": "开箱对比"}},
        content_profile={},
        copy_brief={"topic_subject": "MAXACE 美杜莎4"},
        cover_source_manifest={},
        existing_cover_path=existing_cover,
    )

    assert brief["background_strategy"] == "preserve_reference_background"
    assert "刀身镜面反光区域是实心金属高光，不是开孔、镂空、雕花或缺口。" in brief["critical_detail_notes"]


def test_official_edc_cover_style_can_be_selected_explicitly_without_edc_keywords() -> None:
    prompt = ic._build_platform_cover_image_prompt(
        title="核心结构 看这里",
        platform_key="bilibili",
        rules={
            **ic.PLATFORM_PUBLISH_RULES["bilibili"],
            "cover_style": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        },
        width=1600,
        height=900,
        cover_brief={"product_identity": "普通工具", "visual_brief": "真实手持产品。"},
    )

    assert "风格：EDC 电影英雄封面" in prompt
    assert "主体要像英雄物件" in prompt


def test_cover_style_router_treats_maxace_knife_subject_as_edc_cinematic() -> None:
    style = ic._resolve_cover_image_style_key(
        rules={"cover_style": "tech_showcase"},
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配次顶配",
            "selling_angle": "两款折刀开箱对比",
            "visual_brief": "黑背景下主体锐利、电影感更强",
            "video_type": "开箱对比",
        },
    )

    assert style == ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO


def test_cover_source_selection_contract_does_not_require_dual_subject_compare_frame() -> None:
    contract = ic._build_cover_source_selection_contract(
        content_profile={
            "subject_type": "EDC折刀",
            "summary": "MAXACE 美杜莎4 顶配和次顶配对比开箱",
            "video_theme": "双版差异对比",
        },
        packaging={"highlights": {"product": "MAXACE 美杜莎4", "video_type": "开箱对比"}},
    )

    assert "主体完整展开" in contract
    assert "两件主体同框" not in contract


def test_build_cover_title_lines_splits_brand_subject_and_compare_tail() -> None:
    title_lines = ic._build_cover_title_lines("MAXACE 美杜莎4双版开箱对比")

    assert title_lines == {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "双版开箱对比",
    }


def test_build_cover_title_lines_keeps_model_with_digit_before_action_suffix() -> None:
    title_lines = ic._build_cover_title_lines("MAXACE 美杜莎4 开箱")

    assert title_lines == {
        "top": "MAXACE",
        "main": "美杜莎4",
        "bottom": "开箱",
    }


def test_build_cover_title_layout_plan_promotes_identity_to_brand_model_and_config_subtitle() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="美杜莎4 双版对比",
        cover_brief={
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配与次顶配细节差异",
            "video_type": "开箱对比",
        },
    )

    assert title_lines["brand"] == "MAXACE"
    assert title_lines["main"] == "美杜莎4"
    assert title_lines["sub"] == "顶配vs次顶配"
    assert title_lines["hook"] == "双版本开箱"


def test_build_cover_title_layout_plan_keeps_compare_subtitle_stable_for_medusa_config_line() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="美杜莎4 顶配vs次顶配",
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "两配置做工手感真实对比，铝柄镜面版的颜值与双刃设计更抢眼",
            "video_type": "unboxing",
        },
    )

    assert title_lines["brand"] == "MAXACE"
    assert title_lines["main"] == "美杜莎4"
    assert title_lines["sub"] == "顶配vs次顶配"
    assert title_lines["hook"] == "双版本开箱"


def test_single_tier_unboxing_is_not_mistaken_for_compare() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="maxace蜂巢3顶配开箱",
        cover_brief={
            "product_identity": "maxace蜂巢3顶配EDC折刀",
            "selling_angle": "细节做工与上手质感",
            "video_type": "开箱",
        },
    )

    assert ic._cover_title_line_contains_compare_tail("maxace蜂巢3顶配开箱") is False
    assert "顶配" in title_lines["main"]
    assert "对比" not in title_lines["sub"]
    assert "版本" not in title_lines["sub"]
    assert title_lines["hook"] == "开箱实拍"


def test_build_cover_title_layout_plan_dedupes_brand_and_unboxing_layers() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="maxace蜂巢3顶配开箱",
        cover_brief={
            "product_identity": "maxace蜂巢3顶配EDC折刀",
            "selling_angle": "细节做工与上手质感",
            "video_type": "开箱",
        },
    )

    assert title_lines["brand"] == "maxace"
    assert title_lines["main"] == "蜂巢3顶配"
    assert title_lines["sub"] == ""
    assert title_lines["hook"] == "开箱实拍"


def test_cover_title_semantic_plan_distinguishes_variant_subtitle_and_action_hook() -> None:
    semantic_plan = ctc.build_cover_title_semantic_plan(
        brand="MAXACE",
        main="美杜莎4",
        subtitle="顶配vs次顶配",
        hook="双版本开箱",
        strip_compare_suffix=ic._strip_cover_compare_suffix,
    )

    assert semantic_plan["main"]["slot"] == "identity"
    assert semantic_plan["subtitle"]["slot"] == "variant_compare"
    assert semantic_plan["hook"]["slot"] == "action_evidence"


def test_shared_cover_title_contract_normalizes_alias_fields() -> None:
    normalized = ctc.normalize_cover_title_line_contract(
        {
            "top": "MAXACE",
            "main": "美杜莎4",
            "bottom": "顶配vs次顶配",
        }
    )

    assert normalized == {
        "brand": "MAXACE",
        "top": "MAXACE",
        "main": "美杜莎4",
        "sub": "顶配vs次顶配",
        "bottom": "顶配vs次顶配",
        "hook": "",
    }


def test_build_cover_title_layout_plan_splits_compact_brand_prefix_without_space() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="MAXACE美杜莎4 顶配次顶配开箱",
        cover_brief={
            "product_identity": "MAXACE美杜莎4 顶配次顶配开箱",
            "selling_angle": "顶配与次顶配细节差异",
            "video_type": "开箱对比",
        },
    )

    assert title_lines["brand"] == "MAXACE"
    assert title_lines["main"] == "美杜莎4"
    assert title_lines["sub"] == "顶配vs次顶配"


def test_build_cover_title_layout_plan_strips_product_type_suffix_from_main_title() -> None:
    title_lines = ic._build_cover_title_layout_plan(
        title="美杜莎4 双版对比",
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 EDC折刀 顶配与次顶配",
            "selling_angle": "双配置对比",
            "video_type": "unboxing",
        },
    )

    assert title_lines["main"] == "美杜莎4"


def test_account_metal_cyber_stack_keeps_structured_text_scale_more_constrained() -> None:
    tokens = media_output._title_style_tokens(
        "account_metal_cyber_stack",
        title_lines={"brand": "MAXACE", "main": "美杜莎4", "sub": "顶配vs次顶配", "hook": "双版本对比"},
        cover_style=ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
    )

    assert 48 <= int(tokens["brand"]["size"]) <= 70
    assert 92 <= int(tokens["main"]["size"]) <= 150
    assert 70 <= int(tokens["sub"]["size"]) <= 110
    assert 60 <= int(tokens["hook"]["size"]) <= 90
    assert float(tokens["main"]["safe_width_ratio"]) <= 0.58
    assert str(tokens["hook"]["safe_y_expr"]) == "h*0.80-text_h/2"
    assert len(tokens["main"]["passes"]) == 3
    assert len(tokens["sub"]["passes"]) == 2
    assert len(tokens["hook"]["passes"]) == 2


def test_media_output_resolve_cover_title_prefers_four_layer_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        media_output,
        "get_settings",
        lambda: SimpleNamespace(cover_title=""),
    )

    resolved = media_output._resolve_cover_title(
        {
            "cover_title": {
                "brand": "MAXACE",
                "main": "美杜莎4",
                "sub": "顶配vs次顶配",
                "hook": "双版本开箱",
            }
        }
    )

    assert resolved == {
        "brand": "MAXACE",
        "top": "MAXACE",
        "main": "美杜莎4",
        "sub": "顶配vs次顶配",
        "bottom": "顶配vs次顶配",
        "hook": "双版本开箱",
    }


def test_media_output_sanitize_generated_cover_title_preserves_hook_from_fallback() -> None:
    sanitized = media_output._sanitize_generated_cover_title(
        {"brand": "MAXACE", "main": "美杜莎4", "sub": "顶配vs次顶配"},
        fallback_plan={
            "brand": "MAXACE",
            "main": "美杜莎4",
            "sub": "顶配vs次顶配",
            "hook": "双版本开箱",
        },
        content_profile={
            "subject_brand": "MAXACE",
            "subject_model": "美杜莎4",
            "visible_text": "MAXACE 美杜莎4",
            "video_theme": "双版本开箱",
        },
    )

    assert sanitized["hook"] == "双版本开箱"
    assert sanitized["sub"] == "顶配vs次顶配"


def test_cover_title_overlay_already_applied_invalidates_stale_style_or_lines() -> None:
    payload = {
        "post_title_overlay_applied": True,
        "post_title_overlay_title": "MAXACE美杜莎4 双版对比",
        "post_title_overlay_lines": {
            "brand": "MAXACE",
            "top": "MAXACE",
            "main": "美杜莎4",
            "sub": "顶配vs次顶配",
            "bottom": "顶配vs次顶配",
            "hook": "双版本对比",
        },
        "post_title_overlay_group_style": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        "post_title_overlay_title_style": "account_metal_cyber_stack",
    }
    payload["post_title_overlay_contract"] = ic._build_cover_title_overlay_contract(
        title_lines={"brand": "MAXACE", "top": "MAXACE", "main": "美杜莎4", "sub": "顶配vs次顶配", "bottom": "顶配vs次顶配", "hook": "双版本对比"},
        cover_style=ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        title_style="account_metal_cyber_stack",
    )

    assert ic._cover_title_overlay_already_applied(
        payload,
        title="MAXACE美杜莎4 双版对比",
        title_lines={"brand": "MAXACE", "top": "MAXACE", "main": "美杜莎4", "sub": "顶配vs次顶配", "bottom": "顶配vs次顶配", "hook": "双版本对比"},
        cover_style=ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        title_style="account_metal_cyber_stack",
    )
    assert not ic._cover_title_overlay_already_applied(
        payload,
        title="MAXACE美杜莎4 双版对比",
        title_lines={"brand": "MAXACE", "top": "MAXACE", "main": "美杜莎4", "sub": "顶配次顶配开箱", "bottom": "顶配次顶配开箱", "hook": "双版本对比"},
        cover_style=ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        title_style="account_metal_cyber_stack",
    )
    assert not ic._cover_title_overlay_already_applied(
        payload,
        title="MAXACE美杜莎4 双版对比",
        title_lines={"brand": "MAXACE", "top": "MAXACE", "main": "美杜莎4", "sub": "顶配vs次顶配", "bottom": "顶配vs次顶配", "hook": "双版本对比"},
        cover_style=ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        title_style="double_banner",
    )


def test_generated_cover_title_overlay_remains_enabled_for_codex_backend() -> None:
    assert ic._should_apply_generated_cover_title_overlay(
        source_kind="image_generation",
        image_generation={"backend": "codex_builtin"},
    )
    assert ic._should_apply_generated_cover_title_overlay(
        source_kind="image_generation",
        image_generation={"backend": "dreamina_web"},
    )


def test_platform_cover_prompt_uses_required_main_and_subtitle_lines_for_safe_area() -> None:
    spec = ic._build_platform_cover_prompt_spec(
        title="美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "两配置做工手感真实对比，铝柄镜面版的颜值与双刃设计更抢眼",
            "video_type": "unboxing",
        },
    )

    prompt = ic._build_codex_platform_cover_image_prompt(spec=spec)

    assert "品牌行、主标题行、副标题行、吸睛文案行" in prompt
    assert "必须直接在最终位图里完整渲染这些真实文字" in prompt
    assert "标题区和主体区必须明显分离" in prompt
    assert "主体聚在下半区或两侧下方" in prompt
    assert "主标题「美杜莎4」" in prompt
    assert "副标题「顶配vs次顶配」" in prompt


def test_single_subject_cover_prompt_does_not_inject_compare_contract() -> None:
    brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "maxace蜂巢3顶配EDC折刀",
            "selling_angle": "细节做工与上手质感",
            "video_type": "开箱",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
            "cover_title": "maxace蜂巢3顶配开箱",
        },
        creator_profile_name="FAS",
    )
    spec = ic._build_platform_cover_prompt_spec(
        title="maxace蜂巢3顶配开箱",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1280,
        height=720,
        cover_brief=brief,
    )

    prompt = ic._build_codex_platform_cover_image_prompt(spec=spec)

    assert brief["strategy_axes"]["content_scheme"]["key"] == "unboxing_single_subject_v1"
    assert "双版本开箱" not in prompt
    assert "版本对比" not in prompt
    assert "两件主体" not in prompt
    assert "不要凭空增加第二主体" in prompt


def test_single_subject_cover_prompt_omits_empty_duplicate_subtitle_layer() -> None:
    brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "maxace蜂巢3顶配EDC折刀",
            "selling_angle": "细节做工与上手质感",
            "video_type": "开箱",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
            "cover_title": "maxace蜂巢3顶配开箱",
        },
        creator_profile_name="FAS",
    )
    spec = ic._build_platform_cover_prompt_spec(
        title="maxace蜂巢3顶配开箱",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1280,
        height=720,
        cover_brief=brief,
    )

    prompt = ic._build_codex_platform_cover_image_prompt(spec=spec)

    assert "品牌行「maxace」" in prompt
    assert "主标题「蜂巢3顶配」" in prompt
    assert "吸睛文案「开箱实拍」" in prompt
    assert "副标题「无」" not in prompt
    assert "副标题「开箱」" not in prompt


def test_resolve_overlay_title_style_promotes_edc_cover_to_account_template() -> None:
    cover_style, title_style = ic._resolve_overlay_title_style(
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本开箱对比",
        },
    )

    assert cover_style == ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO
    assert title_style == "account_metal_cyber_stack"


def test_build_platform_cover_prompt_spec_emits_full_cover_director_policy() -> None:
    cover_brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本完整对比展示",
            "video_type": "开箱对比",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
            "cover_title": "MAXACE美杜莎4 顶配vs次顶配",
        },
        creator_profile_name="FAS",
    )
    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1280,
        height=720,
        cover_brief=cover_brief,
    )

    director = spec["director_policy"]
    assert director["direction_version"] == "full_cover_codex_v1"
    assert director["typography_owner"] == "codex_full_cover"
    assert director["style_profile_key"] == "fas_edc_signature_full_cover_v1"
    assert director["base_style_profile_key"] == "edc_cinematic_hero_full_cover_v1"
    assert "横版信息流封面" in director["visual_instruction"]
    assert "metal_3d" in director["headline_effects"]
    assert director["required_title_lines"]["brand"] == "MAXACE"
    assert director["required_title_lines"]["main"] == "美杜莎4"
    assert director["matrix_scheme"]["key"] == "landscape_16_9"
    assert director["content_scheme"]["key"] == "unboxing_single_subject_v1"
    assert director["creator_style_scheme"]["style_profile_key"] == "fas_edc_signature_full_cover_v1"


def test_build_platform_cover_prompt_spec_switches_non_codex_backend_to_local_overlay(monkeypatch) -> None:
    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="minimax_images_api",
        ),
    )

    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE美杜莎4 开箱",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1280,
        height=720,
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "到手开箱看质感和做工",
            "visual_brief": "刀身特写，标题后期叠加。",
            "video_type": "开箱",
        },
    )

    assert spec["cover_backend"] == "minimax_images_api"
    assert spec["typography_owner"] == "local_post_overlay"
    assert spec["director_policy"]["typography_owner"] == "local_post_overlay"
    assert spec["hard_contract"]["post_title_overlay_required"] is True
    assert spec["hard_contract"]["full_bitmap_cover_required"] is False


def test_non_knife_cover_prompt_uses_generic_subject_contract() -> None:
    prompt = ic._build_platform_cover_image_prompt(
        title="小米音箱开箱",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1600,
        height=900,
        cover_brief={
            "product_identity": "小米蓝牙音箱",
            "selling_angle": "外观细节与上手体验",
            "visual_brief": "桌面摆放，主体清楚，层次干净。",
            "video_type": "开箱",
        },
    )

    assert "不允许改刀型" not in prompt
    assert "刀柄、刀身主体" not in prompt
    assert "主体结构、主要部件布局、展示状态" in prompt


def test_provider_safe_cover_prompt_uses_text_free_base_bitmap_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="minimax_images_api",
        ),
    )

    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE 美杜莎4 顶配vs次顶配",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        width=1280,
        height=720,
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "双版本同框对比",
            "visual_brief": "刀身特写，刀柄上可见品牌标识。",
            "video_type": "开箱",
        },
    )

    prompt = ic._build_provider_safe_cover_image_prompt(spec=spec)

    assert "后期统一叠加品牌/型号主标题和配置副标题" in prompt
    assert "底图里不能直接画任何标题字" in prompt
    assert "底图里禁止出现任何可读或半可读的中文、英文、数字、logo 字牌、产品本体铭文" in prompt
    assert "品牌/商品名必须完整保留" not in prompt
    assert "标题结构必须准确完整" not in prompt


def test_standard_cover_matrix_groups_include_four_by_three_master() -> None:
    groups = ic._resolve_standard_cover_matrix_groups()
    keys = [group["key"] for group in groups]

    assert keys == ["landscape_16_9", "landscape_4_3", "portrait_3_4"]
    four_by_three = next(group for group in groups if group["key"] == "landscape_4_3")
    assert tuple(four_by_three["cover_size"]) == (1440, 1080)
    assert "wechat_channels" in four_by_three["members"]
    assert "4:3 横版母版" in four_by_three["visual_instruction"]
    assert "9:16" not in four_by_three["visual_instruction"]


def test_platform_cover_prompt_spec_prefers_matrix_group_visual_instruction() -> None:
    rules = dict(ic.PLATFORM_PUBLISH_RULES["douyin"])
    rules["label"] = "4:3 横版母版"
    rules["cover_size"] = (1440, 1080)
    rules["visual_instruction"] = "4:3 横版母版，主体完整同框，中上区域适合完整主副标题。"

    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE 美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=rules,
        width=1440,
        height=1080,
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本完整对比展示",
            "video_type": "开箱对比",
        },
    )

    assert spec["visual_instruction"] == rules["visual_instruction"]
    assert spec["director_policy"]["visual_instruction"] == rules["visual_instruction"]


def test_annotate_cover_strategy_axes_decouples_matrix_content_and_creator_style() -> None:
    brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本完整对比展示",
            "video_type": "开箱对比",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
            "cover_title": "MAXACE美杜莎4 顶配vs次顶配",
        },
        creator_profile_name="FAS 创作矩阵",
    )

    strategy_axes = dict(brief["strategy_axes"])
    assert strategy_axes["matrix_scheme"]["scope"] == "cross_platform_cover_matrix"
    assert strategy_axes["content_scheme"]["key"] == "unboxing_single_subject_v1"
    assert strategy_axes["content_scheme"]["compare_subject_policy"] == ""
    assert strategy_axes["content_scheme"]["allow_mixed_open_closed_states"] is False
    assert strategy_axes["creator_style_scheme"]["style_profile_key"] == "fas_edc_signature_full_cover_v1"
    assert strategy_axes["subject_fidelity_scheme"]["key"] == "generic_subject_fidelity_v1"
    assert strategy_axes["subject_fidelity_scheme"]["scope"] == "subject_fidelity_contract"
    assert "主要部件数量" in " ".join(strategy_axes["subject_fidelity_scheme"]["generic_constraints"])
    assert "版本映射" not in " ".join(strategy_axes["subject_fidelity_scheme"]["generic_constraints"])


def test_platform_cover_prompt_excludes_packaging_logos_and_printed_cards() -> None:
    spec = ic._build_platform_cover_prompt_spec(
        title="美杜莎4 顶配vs次顶配",
        platform_key="xiaohongshu",
        rules=ic.PLATFORM_PUBLISH_RULES["xiaohongshu"],
        width=1080,
        height=1440,
        cover_brief={
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本同框对比，强调主体完整展示",
            "video_type": "unboxing",
        },
    )

    prompt = ic._build_codex_platform_cover_image_prompt(spec=spec)

    assert "包装盒、卡片、贴纸、说明纸、印刷 logo" in prompt
    assert "不能原样保留在底图里" in prompt
    assert "替换成纯环境材质与无字纹理" in prompt


def test_tech_showcase_style_prompt_is_not_generic_fallback() -> None:
    prompt = ic._cover_image_style_prompt(ic.OFFICIAL_COVER_STYLE_TECH_SHOWCASE)

    assert "风格：科技质感封面" in prompt
    assert "高端产品 hero shot" in prompt


def test_platform_cover_title_never_falls_back_to_body_copy() -> None:
    material = {
        "primary_title": "",
        "body": "这个版本的正文很长，适合发布描述，但绝对不能被拆成封面三行小字，否则手机端会越界也会显得很乱。",
    }
    packaging = {
        "highlights": {
            "title_hook": "先看质感",
            "strongest_selling_point": "锆合金版本",
            "product": "MOT 风灵音叉推牌",
        }
    }

    title = ic._resolve_platform_cover_title(
        material=material,
        packaging=packaging,
        content_profile={},
    )

    assert title == "MOT风灵 锆合金推牌 开箱"
    assert "正文" not in title


def test_cover_group_title_prefers_compact_product_title_over_long_copy() -> None:
    title = ic._resolve_cover_group_title(
        packaging={
            "highlights": {
                "product": "MOT 风灵音叉推牌 锆合金版本",
                "title_hook": "先被质感吸引，再看它是不是你会留下的小物",
                "strongest_selling_point": "锆合金版本",
            }
        },
        content_profile={
            "subject_model": "MOT 风灵音叉推牌 锆合金版本",
            "cover_title": {"main": "MOT 风灵音叉推牌 锆合金版本"},
        },
    )

    assert title == "MOT风灵 锆合金推牌 开箱"


def test_cover_brief_title_preserves_brand_identity_when_llm_omits_it() -> None:
    brief = ic._normalize_cover_brief_payload(
        {
            "cover_title": "锆合金推牌，手感绝了",
            "video_type": "开箱体验",
            "product_identity": "MOT风灵音叉推牌锆合金版",
            "selling_angle": "锆合金仿皮革纹理的丝滑手感",
        },
        fallback={"cover_title": "MOT风灵 锆合金推牌 开箱"},
    )

    assert brief["strategy_source"] == "llm"
    assert brief["cover_title"].startswith("MOT风灵 ")
    assert "锆合金推牌" in brief["cover_title"]


def test_cover_brief_normalizes_critical_detail_notes() -> None:
    brief = ic._normalize_cover_brief_payload(
        {
            "cover_title": "MAXACE 美杜莎4 开箱",
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "critical_detail_notes": [
                "镜面反光区域是实心金属高光，不是开孔。",
                "镜面反光区域是实心金属高光，不是开孔。",
                "刀身该位置保持连续金属轮廓，不得改成洞。",
            ],
        },
        fallback={"cover_title": "MAXACE 美杜莎4 开箱"},
    )

    assert brief["critical_detail_notes"] == [
        "镜面反光区域是实心金属高光，不是开孔。",
        "刀身该位置保持连续金属轮廓，不得改成洞。",
    ]


@pytest.mark.asyncio
async def test_intelligent_cover_brief_uses_llm_summary_instead_of_fixed_format(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeResponse:
        def as_json(self):
            return {
                "cover_title": "风灵推牌 太好玩",
                "video_type": "开箱把玩",
                "product_identity": "MOT 风灵音叉推牌",
                "selling_angle": "锆合金质感和把玩反馈",
                "visual_brief": "产品大、手部真实、标题集中醒目。",
                "critical_detail_notes": ["镜面区域保持实心，不要误画成洞。"],
                "avoid": "不要长句和额外文字。",
            }

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            calls["prompt"] = messages[-1].content
            calls["json_mode"] = kwargs.get("json_mode")
            return FakeResponse()

    monkeypatch.setattr(ic, "get_reasoning_provider", lambda: FakeProvider())
    monkeypatch.setattr(ic, "llm_task_route", lambda *args, **kwargs: nullcontext())

    brief = await ic._build_intelligent_cover_brief(
        video_path=Path("MOT 风灵音叉推牌 锆合金版本.mp4"),
        subtitle_items=[{"text_final": "今天开箱这个锆合金版本，拿到手第一感觉就是质感很扎实。"}],
        content_profile={"subject_model": "MOT 风灵音叉推牌 锆合金版本"},
        copy_brief={"topic_subject": "MOT 风灵音叉推牌", "intent": "unboxing"},
        packaging={"highlights": {"product": "MOT 风灵音叉推牌", "title_hook": "先看质感"}},
    )

    assert brief["strategy_source"] == "llm"
    assert brief["cover_title"] == "风灵推牌 太好玩"
    assert brief["video_type"] == "开箱把玩"
    assert brief["critical_detail_notes"] == ["镜面区域保持实心，不要误画成洞。"]
    assert calls["json_mode"] is True
    assert "不要套固定模板" in str(calls["prompt"])


def test_intelligent_copy_subject_identity_falls_back_to_video_stem() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity({}, Path("MOT 风灵音叉推牌 锆合金版本.mp4"))

    assert profile["subject_model"] == "MOT 风灵音叉推牌 锆合金版本"
    assert profile["search_queries"] == ["MOT 风灵音叉推牌 锆合金版本"]


def test_intelligent_copy_subject_identity_replaces_generic_model() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity(
        {"subject_model": "产品", "summary": "已有摘要"},
        Path("MOT 风灵音叉推牌 锆合金版本.mp4"),
    )

    assert profile["subject_model"] == "MOT 风灵音叉推牌 锆合金版本"
    assert profile["summary"] == "已有摘要"


def test_intelligent_copy_subject_identity_splits_noisy_brand_model_from_stem() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity(
        {"subject_brand": "", "subject_model": "MAXACE美杜莎4 顶配次顶配开箱"},
        Path("MAXACE 美杜莎4 顶配次顶配开箱.mp4"),
    )

    assert profile["subject_brand"] == "MAXACE"
    assert profile["subject_model"] == "美杜莎4"


@pytest.mark.asyncio
async def test_highlight_selection_uses_one_numbered_contact_sheet(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(4):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [{"seek": float(index), "preview": path} for index, path in enumerate(preview_paths)]
    sheet_path = tmp_path / "sheet.jpg"
    calls: dict[str, object] = {}

    def fake_build_contact_sheet(paths, *, output_path=None):
        calls["sheet_paths"] = list(paths)
        calls["sheet_output_path"] = output_path
        sheet_path.write_bytes(b"sheet")
        return sheet_path

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        calls["prompt"] = prompt
        calls["image_paths"] = list(image_paths)
        calls["preferred_provider"] = kwargs.get("preferred_provider")
        calls["preferred_model"] = kwargs.get("preferred_model")
        return '{"best_number":3,"score":0.87,"reason":"主体最大"}'

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"summary": "MOT 风灵音叉推牌开箱"},
        packaging={"highlights": {"title_hook": "先看细节"}},
        contact_sheet_output_path=sheet_path,
    )

    assert selected["index"] == 2
    assert selected["source"] == "llm_full_frame_review"
    assert selected["contact_sheet_path"] == str(sheet_path)
    assert calls["sheet_paths"] == preview_paths
    assert calls["sheet_output_path"] == sheet_path
    assert calls["image_paths"][0] == sheet_path
    assert len(calls["image_paths"]) >= 2
    assert "主要角度完整展示" in calls["prompt"]
    assert "原图" in calls["prompt"]
    assert calls["preferred_provider"] == "minimax"
    assert calls["preferred_model"] == "minimax-m3"


@pytest.mark.asyncio
async def test_highlight_selection_chunks_large_candidate_sets_into_contact_sheets(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(10):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [{"seek": float(index), "preview": path} for index, path in enumerate(preview_paths)]
    sheet_paths: list[Path] = []
    multimodal_calls: list[dict[str, object]] = []

    def fake_build_contact_sheet(paths, *, output_path=None):
        target = output_path or (tmp_path / f"sheet-{len(sheet_paths)+1}.jpg")
        Path(target).write_bytes(b"sheet")
        sheet_paths.append(Path(target))
        return Path(target)

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        multimodal_calls.append(
            {
                "prompt": prompt,
                "image_paths": list(image_paths),
            }
        )
        if len(multimodal_calls) == 1:
            return '{"finalist_numbers":[4,8,9,1],"reason":"这几张主角度更完整，进入最终四宫格"}'
        if len(multimodal_calls) == 2:
            return '{"best_number":3,"score":0.93,"reason":"最终候选里展开态最完整"}'
        if len(multimodal_calls) == 3:
            return '{"best_original_number":9,"ranking_numbers":[9,8,4],"score":0.95,"reason":"9号原图主角度最完整"}'
        raise AssertionError("unexpected multimodal call count")

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"summary": "MAXACE 美杜莎4 开箱"},
        packaging={"highlights": {"product": "MAXACE美杜莎4铝柄高配镜面版直跳刀"}},
        contact_sheet_output_path=tmp_path / "sheet-final.jpg",
    )

    assert selected["index"] == 8
    assert len(multimodal_calls) == 3
    assert len(multimodal_calls[0]["image_paths"]) == 1
    assert len(multimodal_calls[1]["image_paths"]) == 1
    assert len(multimodal_calls[2]["image_paths"]) == 5
    assert "分组 1" in multimodal_calls[0]["prompt"]
    assert "原始序号：[1, 2, 3, 4, 5, 6, 7, 8, 9]" in multimodal_calls[0]["prompt"]
    assert "不要只选唯一 1 张" in multimodal_calls[0]["prompt"]
    assert "前一轮胜出的候选" in multimodal_calls[1]["prompt"]
    assert "原图" in multimodal_calls[2]["prompt"]


def test_extract_cover_source_shortlist_numbers_prefers_valid_finalists() -> None:
    shortlist = ic._extract_cover_source_shortlist_numbers(
        {"finalist_numbers": [4, 8, 9, 99, 4], "best_number": 1},
        original_numbers=[1, 4, 8, 9, 10],
        finalist_limit=4,
    )

    assert shortlist == [4, 8, 9]


def test_extract_cover_source_shortlist_numbers_accepts_valid_original_number_fields() -> None:
    shortlist = ic._extract_cover_source_shortlist_numbers(
        {"valid_original_numbers": [9, 4, 99], "valid_numbers": [8, 4]},
        original_numbers=[4, 8, 9, 10],
        finalist_limit=4,
    )

    assert shortlist == [9, 4, 8]


def test_estimate_cover_subtitle_overlay_risk_distinguishes_subtitle_strip_from_warm_object_block(tmp_path) -> None:
    from PIL import Image, ImageDraw

    subtitle_path = tmp_path / "subtitle-frame.jpg"
    warm_object_path = tmp_path / "warm-object-frame.jpg"

    subtitle_image = Image.new("RGB", (400, 300), (32, 28, 26))
    subtitle_draw = ImageDraw.Draw(subtitle_image)
    subtitle_draw.rectangle((70, 252, 330, 290), fill=(60, 46, 36))
    for start_x in (110, 160, 215, 275):
        subtitle_draw.rounded_rectangle((start_x, 258, start_x + 34, 282), radius=6, fill=(230, 78, 170))
        subtitle_draw.rounded_rectangle((start_x + 3, 261, start_x + 31, 279), radius=4, fill=(246, 214, 84))
    subtitle_image.save(subtitle_path)

    warm_object_image = Image.new("RGB", (400, 300), (32, 28, 26))
    warm_object_draw = ImageDraw.Draw(warm_object_image)
    warm_object_draw.rectangle((70, 252, 330, 290), fill=(60, 46, 36))
    warm_object_draw.rounded_rectangle((230, 220, 385, 292), radius=18, fill=(198, 156, 78))
    warm_object_draw.rounded_rectangle((248, 232, 372, 284), radius=14, fill=(160, 122, 52))
    warm_object_image.save(warm_object_path)

    subtitle_risk = ic._estimate_cover_subtitle_overlay_risk(subtitle_path)
    warm_object_risk = ic._estimate_cover_subtitle_overlay_risk(warm_object_path)

    assert subtitle_risk > warm_object_risk
    assert warm_object_risk < 0.18


@pytest.mark.asyncio
async def test_highlight_selection_uses_ranked_backup_before_heuristic_fallback(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(5):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [
        {"seek": float(index), "preview": path, "subtitle_overlay_risk": 0.0}
        for index, path in enumerate(preview_paths)
    ]

    def fake_build_contact_sheet(paths, *, output_path=None):
        target = output_path or (tmp_path / "sheet.jpg")
        Path(target).write_bytes(b"sheet")
        return Path(target)

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        if "不要只选唯一 1 张" in prompt:
            return '{"finalist_numbers":[1,2,3,4],"reason":"进入终选"}'
        if "原图" in prompt:
            return '{"best_original_number":0}'
        return '{"best_number":1,"ranking_numbers":[4,1,3,2],"score":0.10,"reason":""}'

    async def fail_if_called(**kwargs):
        raise AssertionError("correction round should not be needed when ranked backup is valid")

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)
    monkeypatch.setattr(ic, "_reselect_cover_source_after_hard_contract_violation", fail_if_called)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
        contact_sheet_output_path=tmp_path / "sheet.jpg",
    )

    assert selected["source"] == "llm_contact_sheet_rank_backup"
    assert selected["index"] == 3


@pytest.mark.asyncio
async def test_highlight_selection_reasks_model_before_heuristic_fallback(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(5):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [
        {"seek": float(index), "preview": path, "subtitle_overlay_risk": 0.0}
        for index, path in enumerate(preview_paths)
    ]
    calls: list[str] = []

    def fake_build_contact_sheet(paths, *, output_path=None):
        target = output_path or (tmp_path / "sheet.jpg")
        Path(target).write_bytes(b"sheet")
        return Path(target)

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"finalist_numbers":[1,2,3,4],"reason":"进入终选"}'
        if len(calls) == 2:
            return '{"best_number":1,"ranking_numbers":[1,4,3,2],"score":0.10,"reason":""}'
        if len(calls) == 3:
            return '{"best_original_number":4,"ranking_numbers":[4,3,2],"score":0.91,"reason":"原图复判后这一张展开态更完整"}'
        raise AssertionError("unexpected multimodal call count")

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
        contact_sheet_output_path=tmp_path / "sheet.jpg",
    )

    assert selected["source"] == "llm_full_frame_review"
    assert selected["index"] == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_highlight_selection_uses_full_frame_valid_backup_before_heuristic_fallback(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(5):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [
        {"seek": float(index), "preview": path, "subtitle_overlay_risk": 0.0}
        for index, path in enumerate(preview_paths)
    ]
    calls: list[str] = []

    def fake_build_contact_sheet(paths, *, output_path=None):
        target = output_path or (tmp_path / "sheet.jpg")
        Path(target).write_bytes(b"sheet")
        return Path(target)

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return '{"finalist_numbers":[1,2,3,4],"reason":"进入终选"}'
        if len(calls) == 2:
            return '{"best_number":1,"ranking_numbers":[1,4,3,2],"score":0.10,"reason":""}'
        if len(calls) == 3:
            return '{"best_original_number":1,"valid_original_numbers":[4,3],"ranking_numbers":[1,4,3,2],"score":0.91,"reason":""}'
        raise AssertionError("unexpected multimodal call count")

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
        contact_sheet_output_path=tmp_path / "sheet.jpg",
    )

    assert selected["source"] == "llm_full_frame_review_valid_backup"
    assert selected["index"] == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_highlight_selection_heuristic_fallback_uses_finalists_only(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(6):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [
        {"seek": float(index), "preview": path, "subtitle_overlay_risk": 0.0}
        for index, path in enumerate(preview_paths)
    ]
    fallback_call_lengths: list[int] = []

    def fake_build_contact_sheet(paths, *, output_path=None):
        target = output_path or (tmp_path / "sheet.jpg")
        Path(target).write_bytes(b"sheet")
        return Path(target)

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        if "不要只选唯一 1 张" in prompt:
            return '{"finalist_numbers":[2,4,5,6],"reason":"进入终选"}'
        return '{"best_number":1,"score":0.10,"reason":""}'

    async def fake_reselect(**kwargs):
        return None

    def fake_fallback_numbers(local_candidates, **kwargs):
        fallback_call_lengths.append(len(local_candidates))
        return [1]

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)
    monkeypatch.setattr(ic, "_reselect_cover_source_after_hard_contract_violation", fake_reselect)
    monkeypatch.setattr(ic, "_fallback_hard_contract_cover_candidate_numbers", fake_fallback_numbers)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
        contact_sheet_output_path=tmp_path / "sheet.jpg",
    )

    assert selected["source"] == "heuristic_hard_contract_guard"
    assert fallback_call_lengths[-1] == 4


def test_fallback_hard_contract_cover_candidate_numbers_prefers_low_subtitle_risk_late_compare_frame() -> None:
    ranked = ic._fallback_hard_contract_cover_candidate_numbers(
        [
            {"subtitle_overlay_risk": 0.159},
            {"subtitle_overlay_risk": 0.243},
            {"subtitle_overlay_risk": 0.153},
            {"subtitle_overlay_risk": 0.041},
        ],
        finalist_limit=2,
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
    )

    assert ranked[0] == 4


def test_selection_result_allows_moderate_subtitle_risk_for_compare_when_semantics_are_strong() -> None:
    violates = ic._selection_result_violates_hard_contract(
        {"subtitle_overlay_risk": 0.275},
        content_profile={"subject_type": "直跳刀", "video_theme": "双版差异对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配直跳刀"}},
        score=0.94,
        reason="展开态完整，双主体和版本差异都清晰可见",
    )

    assert violates is False


@pytest.mark.asyncio
async def test_prepare_cover_source_falls_back_when_highlight_selection_fails(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    preview_path = tmp_path / "candidate.jpg"
    preview_path.write_bytes(b"preview")
    calls: dict[str, object] = {}

    monkeypatch.setattr(ic, "get_settings", lambda: SimpleNamespace(cover_candidate_count=1))
    monkeypatch.setattr(ic, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(ic, "_sample_cover_candidates", lambda *args, **kwargs: [{"seek": 4.5, "preview": preview_path}])

    async def fake_extract_frame(path, output_path, seek_sec):
        calls.setdefault("extracts", []).append({"path": path, "output_path": output_path, "seek_sec": seek_sec})
        Path(output_path).write_bytes(b"frame")

    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    source = await ic._prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile={},
        packaging={},
    )

    assert source == smart_copy_cover_source_image_path(material_dir)
    assert source.exists()
    assert calls["extracts"][0]["seek_sec"] == 4.5
    manifest = json.loads(smart_copy_cover_source_manifest_path(material_dir).read_text(encoding="utf-8"))
    assert manifest["source"] == "sampled_reference_pack"
    assert manifest["reference_seek_secs"] == [4.5]
    assert len(manifest["reference_image_paths"]) == 1


@pytest.mark.asyncio
async def test_prepare_cover_source_persists_four_reference_frames_without_contact_sheet(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    preview_paths = []
    for index in range(4):
        preview_path = tmp_path / f"candidate-{index + 1}.jpg"
        preview_path.write_bytes(b"preview")
        preview_paths.append(preview_path)

    monkeypatch.setattr(ic, "get_settings", lambda: SimpleNamespace(cover_candidate_count=4))
    monkeypatch.setattr(ic, "_probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        ic,
        "_sample_cover_candidates",
        lambda *args, **kwargs: [
            {"seek": 4.5 + index, "preview": preview_paths[index]}
            for index in range(4)
        ],
    )
    async def keep_original_order(**kwargs):
        return {
            "primary_number": 1,
            "ranking_numbers": [1, 2, 3, 4],
            "reason": "保持原顺序",
            "used_fallback": False,
        }

    monkeypatch.setattr(ic, "_rank_cover_reference_candidates_for_generation", keep_original_order)

    extracted: list[Path] = []

    async def fake_extract_frame(_path, output_path, _seek_sec):
        extracted.append(Path(output_path))
        Path(output_path).write_bytes(f"frame-{len(extracted)}".encode("utf-8"))

    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    source = await ic._prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile={},
        packaging={},
    )

    manifest = json.loads(smart_copy_cover_source_manifest_path(material_dir).read_text(encoding="utf-8"))

    assert source == smart_copy_cover_source_image_path(material_dir)
    assert [path.name for path in extracted] == [
        "00-highlight-reference-1.jpg",
        "00-highlight-reference-2.jpg",
        "00-highlight-reference-3.jpg",
        "00-highlight-reference-4.jpg",
    ]
    assert manifest["reference_seek_secs"] == [4.5, 5.5, 6.5, 7.5]
    assert len(manifest["reference_image_paths"]) == 4
    assert Path(manifest["reference_image_paths"][0]).read_bytes() == source.read_bytes()
    assert not (material_dir / "_cover" / "00-highlight-candidates-sheet.jpg").exists()


@pytest.mark.asyncio
async def test_prepare_cover_source_reorders_reference_pack_to_frontload_hero_angle(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    preview_paths = []
    for index in range(4):
        preview_path = tmp_path / f"candidate-{index + 1}.jpg"
        preview_path.write_bytes(b"preview")
        preview_paths.append(preview_path)

    monkeypatch.setattr(ic, "get_settings", lambda: SimpleNamespace(cover_candidate_count=4))
    monkeypatch.setattr(ic, "_probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        ic,
        "_sample_cover_candidates",
        lambda *args, **kwargs: [
            {"seek": 4.5 + index, "preview": preview_paths[index]}
            for index in range(4)
        ],
    )
    async def fake_complete_with_images(*args, **kwargs):
        return '{"primary_number":3,"ranking_numbers":[3,4,2,1],"reason":"3号是更完整的正面英雄角度，1号更偏侧面"}'

    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    extracted_seeks: list[float] = []

    async def fake_extract_frame(_path, output_path, seek_sec):
        extracted_seeks.append(float(seek_sec))
        Path(output_path).write_bytes(str(seek_sec).encode("utf-8"))

    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    source = await ic._prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile={"subject_type": "EDC折刀", "video_theme": "顶配次顶配对比"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4 顶配次顶配"}},
    )

    manifest = json.loads(smart_copy_cover_source_manifest_path(material_dir).read_text(encoding="utf-8"))

    assert extracted_seeks == [6.5, 7.5, 5.5, 4.5]
    assert manifest["reference_seek_secs"] == [6.5, 7.5, 5.5, 4.5]
    assert manifest["reference_primary_number"] == 3
    assert manifest["reference_ranking_numbers"] == [3, 4, 2, 1]
    assert "正面英雄角度" in manifest["reference_order_reason"]
    assert Path(manifest["reference_image_paths"][0]).read_bytes() == source.read_bytes()


def test_cover_source_selection_contract_prefers_open_edc_hero_frame() -> None:
    contract = ic._build_cover_source_selection_contract(
        content_profile={"subject_type": "直跳刀", "video_theme": "开箱体验"},
        packaging={"highlights": {"product": "MAXACE美杜莎4铝柄高配镜面版直跳刀"}},
    )

    assert "完整展开" in contract
    assert "闭合态" in contract


def test_list_codex_imagegen_requests_reads_structured_cover_directory(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    request_path = material_dir / "_cover" / "00-cover-landscape_16_9.codex-imagegen.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "source_image_path": "E:/materials/source.jpg",
                "output_path": "E:/materials/00-cover-landscape_16_9.jpg",
                "target_size": {"width": 1920, "height": 1080},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    requests = intelligent_copy_api._list_codex_imagegen_requests(material_dir)

    assert len(requests) == 1
    assert requests[0]["request_path"] == str(request_path)
    assert requests[0]["status"] == "pending_codex_imagegen"
    assert requests[0]["backend"] == "codex_builtin"


def test_build_intelligent_copy_titles_preserves_anchor_coverage_when_explicit_titles_are_weak(monkeypatch) -> None:
    monkeypatch.setattr(
        ic,
        "build_title_candidates",
        lambda **kwargs: ["MAXACE 美杜莎4到底值不值", "这把刀开箱先看细节"],
    )
    monkeypatch.setattr(
        ic,
        "build_fallback_titles",
        lambda **kwargs: ["MAXACE 这次开箱先看细节", "MAXACE 美杜莎4上手到底怎么样"],
    )

    titles = ic._build_intelligent_copy_titles(
        platform_key="douyin",
        rules={"has_title": True, "title_limit": 28, "label": "抖音"},
        copy_brief={
            "topic_subject": "MAXACE 美杜莎4 顶配次顶配",
            "focus_points": ["展开状态", "镜面刀身"],
            "intent": "attention_grabbing",
            "forbidden_terms": [],
            "anchor_terms": ["MAXACE", "美杜莎4"],
            "title_candidates": ["这次开箱先看细节", "MAXACE 到底值不值"],
        },
        content_profile={"subject_brand": "MAXACE", "subject_model": "MAXACE 美杜莎4"},
    )

    anchored = [title for title in titles if "MAXACE" in title or "美杜莎4" in title]
    assert len(anchored) >= 2


def test_build_intelligent_copy_titles_boosts_compare_titles_for_bilibili() -> None:
    titles = ic._build_intelligent_copy_titles(
        platform_key="bilibili",
        rules={"has_title": True, "title_limit": 30, "label": "B站"},
        copy_brief={
            "topic_subject": "MAXACE 美杜莎4",
            "focus_points": ["顶配", "次顶配", "对比"],
            "intent": "attention_grabbing",
            "forbidden_terms": [],
            "anchor_terms": ["MAXACE", "美杜莎4"],
            "title_candidates": ["来看看两兄弟有什么区别"],
        },
        content_profile={"subject_brand": "MAXACE", "subject_model": "MAXACE 美杜莎4"},
    )

    assert any("双版本开箱" in title or "顶配和次顶配" in title for title in titles)
    assert any("MAXACE" in title or "美杜莎4" in title for title in titles[:3])


def test_build_intelligent_copy_brief_derives_compare_defaults_for_unmatched_bilibili_subject() -> None:
    brief = ic._build_intelligent_copy_brief(
        video_path=Path("MAXACE 美杜莎4 顶配次顶配开箱.mp4"),
        subtitle_items=[{"text_final": "今天把顶配和次顶配放一起开箱看看差别"}],
        content_profile={
            "subject_brand": "MAXACE",
            "subject_model": "美杜莎4",
            "subject_type": "EDC跳刀",
            "video_theme": "双版本开箱",
            "engagement_question": "这条视频你会怎么发？",
        },
    )

    assert brief["intent"] == "comparison_unboxing"
    assert brief["question"] != "这条视频你会怎么发？"
    assert brief["focus_points"][:2] == ["顶配", "次顶配"]
    assert any("顶配和次顶配" in title for title in brief["title_candidates"])


def test_build_intelligent_copy_brief_does_not_promote_compare_from_contaminated_summary() -> None:
    brief = ic._build_intelligent_copy_brief(
        video_path=Path("maxace蜂巢3开箱.mp4"),
        subtitle_items=[{"text_final": "这期主要看看蜂巢3的细节、手感和做工。"}],
        content_profile={
            "subject_brand": "maxace",
            "subject_model": "蜂巢3",
            "subject_type": "EDC折刀",
            "summary": "顶配和次顶配双版本开箱，重点看差异。",
            "engagement_question": "你更想先看哪处细节？",
        },
    )

    assert brief["intent"] != "comparison_unboxing"
    assert brief["focus_points"] == ["开箱过程", "细节展示", "上手体验"]
    assert brief["title_candidates"] == []


def test_build_intelligent_copy_description_omits_engagement_question_for_bilibili() -> None:
    description = ic._build_intelligent_copy_description(
        platform_key="bilibili",
        copy_brief={
            "summary": "MAXACE美杜莎4双版本开箱。",
            "question": "你更想先看哪处细节？",
            "focus_points": ["顶配", "次顶配", "细节差异"],
            "forbidden_terms": [],
            "topic_subject": "MAXACE美杜莎4",
            "anchor_terms": ["MAXACE", "美杜莎4"],
        },
    )

    assert "你更想先看哪处细节" not in description
    assert "顶配、次顶配、细节差异" in description


def test_build_publish_safe_copy_summary_avoids_internal_instruction_tone() -> None:
    summary = ic._build_publish_safe_copy_summary(
        subject_label="MAXACE美杜莎4",
        context_text="MAXACE 美杜莎4 顶配次顶配开箱 到手 上手",
    )

    assert "后续文案需要围绕" not in summary
    assert summary == "MAXACE美杜莎4双版本开箱，重点看版本差异、细节展示和上手体验。"


def test_ensure_intelligent_copy_subject_identity_replaces_internal_instruction_summary() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity(
        {
            "subject_brand": "MAXACE",
            "subject_model": "美杜莎4",
            "summary": "EDC跳刀的成片素材，后续文案需要围绕画面、字幕和已核验事实重新创作。",
        },
        Path("MAXACE 美杜莎4 顶配次顶配开箱.mp4"),
    )

    assert profile["summary"] == "美杜莎4双版本开箱，重点看版本差异、细节展示和上手体验。"


@pytest.mark.asyncio
async def test_render_platform_cover_applies_post_overlay_for_codex_generated_cover(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        return {"backend": "codex_builtin", "model": "image2", "size": "1024x1536"}

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda metadata, request, path: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(path),
        },
    )

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert output.exists()
    assert metadata["source"] == "image_generation"
    assert metadata["target_size"] == {"width": 1080, "height": 1440}
    assert calls["generate"]["source_image_path"].name == "base.jpg"
    assert calls["generate"]["width"] == 1080
    assert calls["generate"]["height"] == 1440
    assert calls["fit"]["fit_mode"] == "cover"
    assert "overlay" in calls


@pytest.mark.asyncio
async def test_render_platform_cover_passes_reference_image_pack_to_codex(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    refs = []
    for index in range(4):
        ref = tmp_path / f"reference-{index + 1}.jpg"
        ref.write_bytes(f"ref-{index + 1}".encode("utf-8"))
        refs.append(ref)
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        return {"backend": "codex_builtin", "model": "image2", "size": "1024x1536"}

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_overlay_title_layout(*_args):
        return None

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda metadata, request, path: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(path),
        },
    )

    await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        reference_image_paths=refs,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert Path(calls["generate"]["source_image_path"]).name == "reference-1.jpg"
    assert [Path(path).name for path in calls["generate"]["reference_image_paths"]] == [
        "reference-1.jpg",
        "reference-2.jpg",
        "reference-3.jpg",
        "reference-4.jpg",
    ]


@pytest.mark.asyncio
async def test_render_platform_cover_requires_local_overlay_even_when_bitmap_title_contract_passes(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "bilibili-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        request_path = Path(kwargs["request_path"])
        request_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "codex_full_cover"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify(**kwargs):
        return {
            "bitmap_title_contract_passed": True,
            "main_title_matches": True,
            "subtitle_matches": True,
            "style_consistent": True,
            "detected_main_title": "MAXACE美杜莎4",
            "detected_subtitle": "顶配vs次顶配",
            "reason": "位图标题已满足硬合同",
        }

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_bitmap_title_contract", fake_verify)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda metadata, request, path: {
            "publish_ready": bool(request.get("bitmap_title_contract_passed")),
            "blocking_reasons": [] if request.get("bitmap_title_contract_passed") else ["missing bitmap title contract"],
            "warnings": [],
            "output_path": str(path),
        },
    )

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "顶配与次顶配同框配置差异",
            "visual_brief": "两把刀同框，标题已经在位图中明确呈现。",
            "video_type": "开箱对比",
        },
    )

    assert metadata["publish_ready"] is True
    assert metadata["cover_quality"]["publish_ready"] is True
    request_payload = json.loads(output.with_suffix(".codex-imagegen.json").read_text(encoding="utf-8"))
    assert request_payload["bitmap_title_contract_passed"] is True
    assert "post_title_overlay_applied" not in request_payload
    bitmap_lines = request_payload["bitmap_title_lines"]
    assert "MAXACE" in (bitmap_lines.get("top") or "") or "MAXACE" in (bitmap_lines.get("main") or "")
    assert "美杜莎4" in (bitmap_lines.get("main") or "")
    assert "顶配vs次顶配" in (bitmap_lines.get("bottom") or "")
    assert "overlay" not in calls


@pytest.mark.asyncio
async def test_render_platform_cover_ignores_stale_completed_request_when_prompt_contract_changes(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    output.write_bytes(b"stale")
    request_path = output.with_suffix(".codex-imagegen.json")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(output),
                "prompt": "旧 prompt",
                "cover_hard_contract": {"required_title_lines": {"main": "旧标题"}},
                "cover_director_policy": {"typography_owner": "local_post_overlay"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        Path(kwargs["request_path"]).write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "prompt": kwargs["prompt"],
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "local_post_overlay"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        return {"unexpected_bitmap_text_detected": False, "detected_text": [], "reason": ""}

    async def fake_overlay_title_layout(*_args):
        return None

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "顶配与次顶配同框配置差异",
            "visual_brief": "两把刀同框，标题后期统一叠加。",
            "video_type": "开箱对比",
        },
    )

    assert metadata["source"] == "image_generation"
    assert "generate" in calls
    updated_payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert updated_payload["prompt"] == calls["generate"]["prompt"]


@pytest.mark.asyncio
async def test_render_platform_cover_blocks_unexpected_bitmap_text_for_local_overlay_flow(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        request_path = Path(kwargs["request_path"])
        request_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "local_post_overlay"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        return {
            "unexpected_bitmap_text_detected": True,
            "detected_text": ["巅峰之作"],
            "reason": "顶部存在额外大字字牌",
        }

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "顶配与次顶配同框配置差异",
            "visual_brief": "两把刀同框，标题后期统一叠加。",
            "video_type": "开箱对比",
        },
    )

    assert metadata["publish_ready"] is False
    assert any("额外可读文字" in reason for reason in metadata["blocking_reasons"])
    request_payload = json.loads(output.with_suffix(".codex-imagegen.json").read_text(encoding="utf-8"))
    assert request_payload["bitmap_unexpected_text_detected"] is True
    assert request_payload["bitmap_unexpected_text_detected_lines"] == ["巅峰之作"]
    assert "overlay" not in calls


@pytest.mark.asyncio
async def test_render_platform_cover_blocks_when_unexpected_bitmap_text_verification_is_unavailable(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"generated")
        request_path = Path(kwargs["request_path"])
        request_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "local_post_overlay"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        return {}

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "顶配与次顶配同框配置差异",
            "visual_brief": "两把刀同框，标题后期统一叠加。",
            "video_type": "开箱对比",
        },
    )

    assert metadata["publish_ready"] is False
    assert any("封面位图额外文字校验未产出有效结论" in reason for reason in metadata["blocking_reasons"])
    request_payload = json.loads(output.with_suffix(".codex-imagegen.json").read_text(encoding="utf-8"))
    assert request_payload["bitmap_unexpected_text_check_unavailable"] is True
    assert request_payload["bitmap_unexpected_text_reason"] == "unexpected_bitmap_text_verification_unavailable"


@pytest.mark.asyncio
async def test_verify_generated_cover_has_unexpected_bitmap_text_uses_longer_timeout_budget(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"image")
    captured: dict[str, object] = {}

    async def fake_complete_with_images(prompt, images, **kwargs):
        captured["kwargs"] = kwargs
        return '{"unexpected_bitmap_text_detected":false,"detected_text":[],"reason":"ok"}'

    async def fake_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)
    monkeypatch.setattr(ic.asyncio, "wait_for", fake_wait_for)

    result = await ic._verify_generated_cover_has_unexpected_bitmap_text(output_path=output)

    assert result["unexpected_bitmap_text_detected"] is False
    assert captured["timeout"] == 30.0
    assert captured["kwargs"]["preferred_provider"] == "minimax"
    assert captured["kwargs"]["preferred_model"] == "minimax-m3"


@pytest.mark.asyncio
async def test_render_platform_cover_does_not_hard_gate_compare_subject_contract_for_dual_subject_copy(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        request_path = Path(kwargs["request_path"])
        request_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "local_post_overlay"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        return {"unexpected_bitmap_text_detected": False, "detected_text": [], "reason": ""}

    async def fake_verify_compare_subject(**kwargs):
        calls["compare"] = kwargs
        return {
            "compare_subject_contract_passed": False,
            "reason": "竖版构图过近，第二件主体只剩局部",
        }

    async def fake_overlay_title_layout(*_args):
        return None

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)
    monkeypatch.setattr(ic, "_verify_generated_cover_compare_subject_contract", fake_verify_compare_subject)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "双版本完整对比展示，做工和细节表现",
            "visual_brief": "两把刀同框，标题后期统一叠加。",
            "video_type": "开箱对比",
        },
    )

    assert not any("双主体展示不满足硬合同" in reason for reason in metadata["blocking_reasons"])
    request_payload = json.loads(output.with_suffix(".codex-imagegen.json").read_text(encoding="utf-8"))
    assert request_payload["cover_hard_contract"]["compare_subject_pair_required"] is False
    assert "compare_subject_contract_passed" not in request_payload
    assert "compare" not in calls


@pytest.mark.asyncio
async def test_ensure_generated_cover_title_contract_ready_ignores_legacy_compare_subject_gate_for_local_overlay(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"final")
    pre_overlay = tmp_path / "cover.pre-overlay.jpg"
    pre_overlay.write_bytes(b"raw")
    request_path = tmp_path / "cover.codex-imagegen.json"
    request_payload = {
        "status": "completed",
        "backend": "codex_builtin",
        "output_path": str(output),
        "pre_overlay_output_path": str(pre_overlay),
        "cover_director_policy": {"typography_owner": "local_post_overlay"},
        "cover_hard_contract": {"compare_subject_pair_required": True},
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
    calls: dict[str, Path] = {}

    async def fake_verify_unexpected_text(**kwargs):
        calls["unexpected"] = kwargs["output_path"]
        return {"unexpected_bitmap_text_detected": False, "detected_text": [], "reason": ""}

    async def fake_verify_compare_subject(**kwargs):
        calls["compare"] = kwargs["output_path"]
        return {"compare_subject_contract_passed": True, "reason": "ok"}

    async def fake_verify_bitmap_title_contract(**kwargs):
        return {}

    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)
    monkeypatch.setattr(ic, "_verify_generated_cover_compare_subject_contract", fake_verify_compare_subject)
    monkeypatch.setattr(ic, "_verify_generated_cover_bitmap_title_contract", fake_verify_bitmap_title_contract)

    await ic._ensure_generated_cover_title_contract_ready(
        request_path=request_path,
        request_payload=request_payload,
        output_path=output,
        title="MAXACE美杜莎4 顶配vs次顶配",
        title_lines={"top": "MAXACE", "main": "美杜莎4", "bottom": "顶配vs次顶配"},
        rules=ic.PLATFORM_PUBLISH_RULES["xiaohongshu"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "双版本完整对比展示，做工和细节表现",
            "visual_brief": "两把刀同框，标题后期统一叠加。",
            "video_type": "开箱对比",
        },
        source_kind="image_generation",
        image_generation={"backend": "codex_builtin", "status": "completed", "output_path": str(output)},
        allow_overlay=False,
    )

    assert calls["unexpected"] == pre_overlay
    assert "compare" not in calls
    refreshed = json.loads(request_path.read_text(encoding="utf-8"))
    assert "bitmap_title_contract_passed" not in refreshed
    assert "bitmap_title_contract_check_unavailable" not in refreshed
    assert "bitmap_title_contract_reason" not in refreshed


@pytest.mark.asyncio
async def test_compare_subject_contract_prompt_rejects_invented_second_subject(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"cover")
    captured: dict[str, object] = {}

    async def fake_run_cover_visual_json_verification(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return {"compare_subject_contract_passed": True, "reason": "ok"}, ""

    monkeypatch.setattr(ic, "_run_cover_visual_json_verification", fake_run_cover_visual_json_verification)

    await ic._verify_generated_cover_compare_subject_contract(output_path=output, request_payload={})

    prompt = str(captured["prompt"])
    assert "真实主商品本身" in prompt
    assert "不把包装盒" in prompt
    assert "凭空增加误导性的第二主体" in prompt


@pytest.mark.asyncio
async def test_verify_generated_cover_compare_subject_contract_uses_longer_budget(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"cover")
    calls: dict[str, object] = {}

    async def fake_run_cover_visual_json_verification(**kwargs):
        calls["timeout_sec"] = kwargs.get("timeout_sec")
        calls["attempts"] = kwargs.get("attempts")
        return {"compare_subject_contract_passed": True, "reason": "ok"}, ""

    monkeypatch.setattr(ic, "_run_cover_visual_json_verification", fake_run_cover_visual_json_verification)

    result = await ic._verify_generated_cover_compare_subject_contract(output_path=output, request_payload={})

    assert result["compare_subject_contract_passed"] is True
    assert calls["timeout_sec"] == 45.0
    assert calls["attempts"] == 3


def test_build_platform_cover_prompt_spec_uses_content_scheme_portrait_compare_instruction() -> None:
    cover_brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "顶配与次顶配双版本完整开箱对比，做工细节和材质质感一眼看懂",
            "visual_brief": "主体真实，手持展示，标题舞台放在上中部。",
            "video_type": "开箱体验",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        },
        creator_profile_name="FAS",
    )
    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE 美杜莎4 顶配vs次顶配",
        platform_key="xiaohongshu",
        rules={
            **ic.PLATFORM_PUBLISH_RULES["xiaohongshu"],
            "label": "3:4 竖版母版",
            "visual_instruction": "3:4 竖版母版，强调质感与主体完整展示，上半区适合品牌与主标题，下半区保留产品和手持关系，不要挤压主体。",
        },
        width=1080,
        height=1440,
        cover_brief=cover_brief,
    )
    assert spec["hard_contract"]["compare_subject_pair_required"] is False
    assert spec["director_policy"]["supports_compare_subject_pair"] is False
    prompt = ic._build_platform_cover_image_prompt(
        title="MAXACE 美杜莎4 顶配vs次顶配",
        platform_key="xiaohongshu",
        rules={
            **ic.PLATFORM_PUBLISH_RULES["xiaohongshu"],
            "label": "3:4 竖版母版",
            "visual_instruction": "3:4 竖版母版，强调质感与主体完整展示，上半区适合品牌与主标题，下半区保留产品和手持关系，不要挤压主体。",
        },
        width=1080,
        height=1440,
        cover_brief=cover_brief,
    )
    assert "不要凭空增加第二主体" in prompt
    assert "主体保真通用约束" in prompt
    assert "保留主体主要轮廓、比例关系、主要部件数量与相对位置" in prompt
    assert "双主体编辑预算必须极小" not in prompt
    assert "标题堆叠必须更紧凑地上收" in prompt
    assert "画面中部要保留主主体展示通道" in prompt


@pytest.mark.asyncio
async def test_render_platform_cover_keeps_original_reference_for_compare_wording(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        request_path = Path(kwargs["request_path"])
        request_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(output),
                    "prompt": kwargs["prompt"],
                    "cover_hard_contract": kwargs["hard_contract"],
                    "cover_director_policy": {"typography_owner": "local_post_overlay"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"backend": "codex_builtin", "status": "completed", "output_path": str(output)}

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        return {"unexpected_bitmap_text_detected": False, "detected_text": [], "reason": ""}

    async def fake_verify_compare_subject(**kwargs):
        return {"compare_subject_contract_passed": True, "reason": ""}

    async def fake_overlay_title_layout(*_args):
        return None

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)
    monkeypatch.setattr(ic, "_verify_generated_cover_compare_subject_contract", fake_verify_compare_subject)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    cover_brief = ic._annotate_cover_strategy_axes(
        {
            "product_identity": "美杜莎4 顶配vs次顶配",
            "selling_angle": "双版本完整对比展示，做工和细节表现",
            "visual_brief": "主体真实，标题后期统一叠加。",
            "video_type": "开箱对比",
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        }
    )

    await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief=cover_brief,
    )

    assert len(calls["generate"]["reference_image_paths"]) == 1
    assert Path(calls["generate"]["source_image_path"]).name == "base.jpg"
    assert Path(calls["generate"]["reference_image_paths"][0]).name == "base.jpg"


@pytest.mark.asyncio
async def test_generate_edited_cover_image_uses_dreamina_web_backend(tmp_path, monkeypatch) -> None:
    source = tmp_path / "reference.jpg"
    source.write_bytes(b"reference")
    output = tmp_path / "dreamina-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="dreamina_web",
            intelligent_copy_cover_image_model="5.0",
            intelligent_copy_cover_image_quality="2k",
            intelligent_copy_cover_image_timeout_sec=120,
            intelligent_copy_cover_dreamina_command="node",
            intelligent_copy_cover_dreamina_runner_script="C:/runner/dreamina-web-cdp.js",
            intelligent_copy_cover_dreamina_cdp_base_url="http://127.0.0.1:9222",
            intelligent_copy_cover_dreamina_cookie_source_base_url="http://127.0.0.1:9222",
            intelligent_copy_cover_dreamina_page_url="https://jimeng.jianying.com/ai-tool/generate/?type=image",
            intelligent_copy_cover_dreamina_page_url_pattern="jimeng.jianying.com/ai-tool/generate",
            intelligent_copy_cover_dreamina_user_data_dir="C:/profile",
            intelligent_copy_cover_dreamina_headless_user_data_dir="C:/profile-headless",
            intelligent_copy_cover_dreamina_template_path="C:/template.json",
            intelligent_copy_cover_dreamina_submit_state_path="C:/submit-state.json",
            intelligent_copy_cover_dreamina_executable_path="",
            intelligent_copy_cover_dreamina_http_replay_enabled=True,
            intelligent_copy_cover_dreamina_auto_launch=True,
            intelligent_copy_cover_dreamina_headless=True,
            intelligent_copy_cover_dreamina_keep_alive=False,
            intelligent_copy_cover_dreamina_poll_interval_ms=5000,
            intelligent_copy_cover_dreamina_poll_timeout_ms=300000,
            intelligent_copy_cover_dreamina_submit_timeout_ms=60000,
            intelligent_copy_cover_dreamina_capture_timeout_ms=120000,
            intelligent_copy_cover_dreamina_min_submit_interval_ms=45000,
        ),
    )

    async def fake_request_dreamina_web_generation(*, settings, request_spec):
        calls["request_spec"] = request_spec
        return {
            "result": {
                "url": "https://example.com/generated.jpg",
                "selectedCandidateIndex": 2,
                "selectedCandidate": {"url": "https://example.com/generated.jpg", "width": 1536, "height": 1024},
                "candidates": [
                    {"url": "https://example.com/1.jpg", "width": 1024, "height": 1024},
                    {"url": "https://example.com/2.jpg", "width": 1536, "height": 1024},
                    {"url": "https://example.com/generated.jpg", "width": 1536, "height": 1024},
                    {"url": "https://example.com/4.jpg", "width": 1024, "height": 1536},
                ],
            },
            "generationStatus": "submitted_via_page_and_polled",
            "responseMeta": {
                "transport": "cdp_page_submit",
                "submit_id": "submit-123",
                "history_url": "https://jimeng.jianying.com/history",
                "resolved_model_version": "high_aes_general_v50",
            },
        }

    async def fake_download(url: str, output_path: Path, *, timeout_sec: float) -> None:
        calls["download"] = {"url": url, "output_path": output_path, "timeout_sec": timeout_sec}
        output_path.write_bytes(b"dreamina")

    monkeypatch.setattr(imagegen, "_request_dreamina_web_generation", fake_request_dreamina_web_generation)
    monkeypatch.setattr(imagegen, "_download_generated_image", fake_download)

    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        prompt="主体大，标题集中，空间结构稳定",
        width=1080,
        height=1920,
    )

    assert output.read_bytes() == b"dreamina"
    assert calls["request_spec"]["ratio"] == "9:16"
    assert calls["request_spec"]["model"] == "5.0"
    assert calls["request_spec"]["reference_images"][0]["path"] == str(source)
    assert "MAXACE" not in calls["request_spec"]["prompt"]
    assert "折刀" not in calls["request_spec"]["prompt"]
    assert metadata["backend"] == "dreamina_web"
    assert metadata["candidate_count"] == 4
    assert metadata["selected_candidate_index"] == 2
    assert metadata["transport"] == "cdp_page_submit"
    assert metadata["submit_id"] == "submit-123"


@pytest.mark.asyncio
async def test_generate_edited_cover_image_falls_back_when_dreamina_consistency_ranking_times_out(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "reference.jpg"
    source.write_bytes(b"reference")
    output = tmp_path / "dreamina-cover.jpg"
    calls: dict[str, object] = {"downloads": []}

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="dreamina_web",
            intelligent_copy_cover_image_model="5.0",
            intelligent_copy_cover_image_timeout_sec=90,
        ),
    )

    async def fake_request_dreamina_web_generation(*, settings, request_spec):
        return {
            "result": {
                "url": "https://example.com/selected.png",
                "selectedCandidateIndex": 1,
                "selectedCandidate": {"url": "https://example.com/selected.png"},
                "candidates": [
                    {"url": "https://example.com/candidate-1.png"},
                    {"url": "https://example.com/selected.png"},
                ],
            },
            "generationStatus": "submitted_via_page_and_polled",
            "responseMeta": {
                "transport": "cdp_page_submit",
                "submit_id": "submit-timeout",
                "resolved_model_version": "high_aes_general_v50",
            },
        }

    async def fake_download(url: str, output_path: Path, *, timeout_sec: float) -> None:
        calls["downloads"].append(url)
        output_path.write_bytes(url.encode("utf-8"))

    async def fake_rank(*, source_image_path: Path, candidate_paths: list[Path], prompt: str):
        raise TimeoutError("ranking stalled")

    monkeypatch.setattr(imagegen, "_request_dreamina_web_generation", fake_request_dreamina_web_generation)
    monkeypatch.setattr(imagegen, "_download_generated_image", fake_download)
    monkeypatch.setattr(imagegen, "_rank_dreamina_candidates_by_reference", fake_rank)

    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        prompt="主体一致，标题完整",
        width=1600,
        height=900,
    )

    assert metadata["status"] == "completed"
    assert metadata["selected_candidate_index"] == 1
    assert metadata["candidate_consistency_assessment"]["selected_reason"] == "consistency_ranking_failed"
    assert metadata["candidate_consistency_assessment"]["timeout_sec"] == 45.0
    assert output.read_text(encoding="utf-8") == "https://example.com/selected.png"
    assert calls["downloads"][-1] == "https://example.com/selected.png"


def test_sanitize_dreamina_prompt_preserves_identity_and_title_lines() -> None:
    prompt = (
        "封面主题：MAXACE 美杜莎4双版开箱对比\n"
        "标题：美杜莎4双版开箱对比\n"
        "标题必须完整渲染：美杜莎4双版开箱对比\n"
        "主体识别：MAXACE美杜莎4 EDC折刀（顶配与次顶配）\n"
        "品牌/商品名必须完整保留：MAXACE美杜莎4\n"
        "画面 brief：双刀并排展示，聚焦刀身\n"
        "重点强调商品细节一致性：保留轮廓、比例、开孔、转轴、刀型、纹理分区和主要部件位置，不改款，不变形。"
    )

    sanitized = imagegen._sanitize_dreamina_prompt(prompt)

    assert "封面主题：MAXACE 美杜莎4双版开箱对比" in sanitized
    assert "标题：美杜莎4双版开箱对比" in sanitized
    assert "标题必须完整渲染：美杜莎4双版开箱对比" in sanitized
    assert "主体识别：MAXACE美杜莎4 EDC折刀（顶配与次顶配）" in sanitized
    assert "品牌/商品名必须完整保留：MAXACE美杜莎4" in sanitized
    assert "聚焦主体" in sanitized
    assert "结构细节" in sanitized
    assert "双刀并排展示" not in sanitized


def test_resolve_dreamina_runner_timeout_sec_covers_poll_and_submit_windows() -> None:
    settings = SimpleNamespace(
        intelligent_copy_cover_image_timeout_sec=90,
        intelligent_copy_cover_dreamina_poll_timeout_ms=300000,
        intelligent_copy_cover_dreamina_submit_timeout_ms=60000,
    )

    assert imagegen._resolve_dreamina_runner_timeout_sec(settings) == 390


@pytest.mark.asyncio
async def test_request_dreamina_web_generation_uses_backend_aware_timeout(tmp_path, monkeypatch) -> None:
    runner_script = tmp_path / "dreamina_web_cdp.mjs"
    runner_script.write_text("export {};\n", encoding="utf-8")
    bridge_script = tmp_path / "dreamina_request_bridge.mjs"
    bridge_script.write_text("bridge\n", encoding="utf-8")

    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self, payload: bytes = b"") -> tuple[bytes, bytes]:
            captured["payload"] = json.loads(payload.decode("utf-8"))
            return (json.dumps({"result": {"url": "https://example.com/generated.jpg"}}).encode("utf-8"), b"")

        def kill(self) -> None:
            captured["killed"] = True

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["argv"] = args
        captured["cwd"] = kwargs.get("cwd")
        return FakeProcess()

    async def fake_wait_for(awaitable, timeout=None):
        captured["timeout"] = timeout
        return await awaitable

    monkeypatch.setattr(imagegen, "_resolve_dreamina_runner_script", lambda _settings: runner_script)
    monkeypatch.setattr(imagegen, "asyncio", SimpleNamespace(
        create_subprocess_exec=fake_create_subprocess_exec,
        wait_for=fake_wait_for,
        subprocess=asyncio.subprocess,
    ))

    settings = SimpleNamespace(
        intelligent_copy_cover_image_timeout_sec=90,
        intelligent_copy_cover_dreamina_command="node",
        intelligent_copy_cover_dreamina_runner_script=str(runner_script),
        intelligent_copy_cover_dreamina_poll_timeout_ms=300000,
        intelligent_copy_cover_dreamina_submit_timeout_ms=60000,
    )

    await imagegen._request_dreamina_web_generation(
        settings=settings,
        request_spec={"prompt": "生成封面"},
    )

    assert captured["timeout"] == 390.0


@pytest.mark.asyncio
async def test_platform_cover_group_reuses_one_generated_cover_for_same_class(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    (tmp_path / "_cover").mkdir()
    cache: dict[str, dict[str, object]] = {}
    render_calls: list[dict[str, object]] = []
    fit_calls: list[dict[str, object]] = []

    async def fake_render_platform_cover(**kwargs):
        render_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"group cover")
        return {
            "source": "image_generation",
            "platform": kwargs["platform_key"],
            "target_size": {"width": 1600, "height": 900},
            "publish_ready": True,
            "blocking_reasons": [],
            "image_generation": {"backend": "codex_builtin", "status": "completed"},
        }

    def fake_fit_image_to_canvas(**kwargs):
        fit_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"platform cover")

    monkeypatch.setattr(ic, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)

    bilibili_group = ic._resolve_platform_cover_group(
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
    )
    youtube_group = ic._resolve_platform_cover_group(
        platform_key="youtube",
        rules=ic.PLATFORM_PUBLISH_RULES["youtube"],
    )

    bilibili = await ic._render_or_reuse_platform_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "01-bilibili-cover.jpg",
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT风灵 锆合金",
        platform_key="bilibili",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_group=bilibili_group,
    )
    youtube = await ic._render_or_reuse_platform_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "07-youtube-cover.jpg",
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT风灵 锆合金",
        platform_key="youtube",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["youtube"],
        cover_group=youtube_group,
    )

    assert len(render_calls) == 1
    assert render_calls[0]["output_path"] == tmp_path / "_cover" / "00-cover-landscape_16_9.jpg"
    assert bilibili["cover_group"]["key"] == "landscape_16_9"
    assert youtube["cover_group"]["key"] == "landscape_16_9"
    assert bilibili["publish_ready"] is True
    assert youtube["publish_ready"] is True
    assert len(fit_calls) == 2


def test_toutiao_cover_group_uses_landscape_16_9_matrix() -> None:
    group = ic._resolve_platform_cover_group(
        platform_key="toutiao",
        rules=ic.PLATFORM_PUBLISH_RULES["toutiao"],
    )

    assert group["key"] == "landscape_16_9"
    assert tuple(group["cover_size"]) == (1600, 900)
    assert "toutiao" in list(group["members"] or [])


def test_existing_cover_option_reuses_detected_cover_without_imagegen(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "existing-cover.jpg"
    existing.write_bytes(b"existing")
    cache: dict[str, dict[str, object]] = {}
    fit_calls: list[dict[str, object]] = []

    def fake_fit_image_to_canvas(**kwargs):
        fit_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"fit")

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    cover_group = ic._resolve_platform_cover_group(
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
    )

    metadata = ic._render_or_reuse_existing_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "01-bilibili-cover.jpg",
        existing_cover_path=existing,
        platform_key="bilibili",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_group=cover_group,
    )

    assert metadata["source"] == "cover_group_reuse"
    assert metadata["publish_ready"] is True
    assert metadata["image_generation"] is None
    assert fit_calls[0]["source_path"] == existing
    assert fit_calls[0]["output_path"] == tmp_path / "00-cover-landscape_16_9.jpg"


def test_materialize_platform_cover_from_group_keeps_blockers_when_existing_artifact_is_only_fallback(tmp_path, monkeypatch) -> None:
    group_output = tmp_path / "00-cover-portrait_3_4.jpg"
    group_output.write_bytes(b"group cover")
    output = tmp_path / "02-douyin-cover.jpg"
    fit_calls: list[dict[str, object]] = []

    def fake_fit_image_to_canvas(**kwargs):
        fit_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"platform cover")

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)

    metadata = ic._materialize_platform_cover_from_group(
        group_metadata={
            "publish_ready": False,
            "blocking_reasons": ["封面图像生成重试后仍失败：Dreamina runner timed out after 90s"],
            "warnings": [],
            "image_generation": None,
        },
        group_output_path=group_output,
        output_path=output,
        platform_key="douyin",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_group={
            "key": "portrait_3_4",
            "label": "3:4 竖版通用封面",
            "members": ["douyin"],
        },
    )

    assert metadata["publish_ready"] is False
    assert metadata["blocking_reasons"] == ["封面图像生成重试后仍失败：Dreamina runner timed out after 90s"]
    assert fit_calls == []
    assert not output.exists()


def test_prepare_structured_smart_copy_layout_removes_publication_runtime_dir(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    runtime_dir = material_dir / "_publication_runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "stale.publishable.mp4").write_bytes(b"stale")

    ic._prepare_structured_smart_copy_layout(material_dir)

    assert not runtime_dir.exists()


def test_restore_platform_cover_path_clears_blocked_group_reuse_cover(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    platform_cover = material_dir / "01-bilibili-cover.jpg"
    platform_cover.write_bytes(b"stale-cover")
    material = {
        "key": "bilibili",
        "cover_path": str(platform_cover),
        "cover_generation": {
            "source": "cover_group_reuse",
            "publish_ready": False,
            "blocking_reasons": ["完整封面位图标题校验未完成，不能放行到最终封面"],
        },
    }

    ic._restore_platform_cover_path(material=material, material_dir=material_dir, index=1)

    assert "cover_path" not in material
    assert not platform_cover.exists()


def test_restore_platform_cover_path_recovers_group_cover_despite_stale_blocked_verdict(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_cover = material_dir / "_cover" / "00-cover-portrait_3_4.jpg"
    group_cover.parent.mkdir()
    group_cover.write_bytes(b"group-cover")
    material = {
        "key": "xiaohongshu",
        "cover_generation": {
            "source": "cover_group_reuse",
            "publish_ready": False,
            "blocking_reasons": ["封面主标题未稳定锁定品牌/型号，存在内容签名漂移风险"],
            "cover_group": {
                "cover_path": str(group_cover),
            },
        },
    }

    ic._restore_platform_cover_path(material=material, material_dir=material_dir, index=2)

    restored_path = material_dir / "02-xiaohongshu-cover.jpg"
    assert material["cover_path"] == str(restored_path)
    assert restored_path.exists()


def test_synchronize_publishable_root_files_prunes_stale_platform_artifacts(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    stale_x_cover = material_dir / "01-x-cover.jpg"
    stale_x_md = material_dir / "01-x.md"
    bilibili_cover = material_dir / "01-bilibili-cover.jpg"
    bilibili_md = material_dir / "01-bilibili.md"
    x_cover = material_dir / "08-x-cover.jpg"
    x_md = material_dir / "08-x.md"
    for path in (stale_x_cover, stale_x_md, bilibili_cover, bilibili_md, x_cover, x_md):
        path.write_bytes(b"stale")

    ic._synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (1, {"key": "bilibili", "cover_path": "", "full_copy": "b"}),
            (8, {"key": "x", "cover_path": str(x_cover), "full_copy": "x"}),
        ],
    )

    assert not stale_x_cover.exists()
    assert not stale_x_md.exists()
    assert not bilibili_cover.exists()
    assert bilibili_md.exists()
    assert x_cover.exists()
    assert x_md.exists()


def test_upgrade_existing_intelligent_copy_result_keeps_pending_group_cover_blocked(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    group_cover = material_dir / "00-cover-landscape_16_9.jpg"
    group_cover.write_bytes(b"group-cover")
    platform_cover = material_dir / "01-bilibili-cover.jpg"
    platform_cover.write_bytes(b"platform-cover")
    request_path = material_dir / "00-cover-landscape_16_9.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "created_at": "2026-06-02T10:00:00+08:00",
                "output_path": str(group_cover),
                "target_size": {"width": 1920, "height": 1080},
                "image_generation": {
                    "status": "pending_codex_imagegen",
                    "backend": "codex_builtin",
                    "output_path": str(group_cover),
                    "request_path": str(request_path),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "csv"},
                        "titles": ["MAXACE美杜莎4双版对比"],
                        "primary_title": "MAXACE美杜莎4双版对比",
                        "title_copy_all": "1. MAXACE美杜莎4双版对比",
                        "body": "双配置差异先看封面和结构。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "MAXACE, 美杜莎4",
                        "full_copy": "MAXACE美杜莎4双版对比\n\n双配置差异先看封面和结构。",
                        "cover_path": str(platform_cover),
                        "cover_generation": {
                            "source": "cover_group_reuse",
                            "publish_ready": True,
                            "blocking_reasons": [],
                            "cover_group": {
                                "key": "landscape_16_9",
                                "label": "16:9",
                                "cover_path": str(group_cover),
                                "members": ["bilibili"],
                            },
                            "group_generation": {
                                "source": "image_generation",
                                "publish_ready": True,
                                "blocking_reasons": [],
                                "cover_group": {
                                    "key": "landscape_16_9",
                                    "label": "16:9",
                                    "cover_path": str(group_cover),
                                    "members": ["bilibili"],
                                },
                                "image_generation": {
                                    "status": "pending_codex_imagegen",
                                    "backend": "codex_builtin",
                                    "output_path": str(group_cover),
                                    "request_path": str(request_path),
                                },
                            },
                            "image_generation": {
                                "status": "pending_codex_imagegen",
                                "backend": "codex_builtin",
                                "output_path": str(group_cover),
                                "request_path": str(request_path),
                            },
                        },
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ic, "build_cached_publication_scheme", lambda **_kwargs: {})

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["bilibili"],
        browser="chrome",
    )

    material = result["platforms"][0]
    assert material["publish_ready"] is False
    assert material["cover_generation"]["publish_ready"] is False
    assert "封面等待 Codex 内置 imagegen 执行完成" in material["cover_generation"]["blocking_reasons"]
    assert "封面等待 Codex 内置 imagegen 执行完成" in material["blocking_reasons"]
    assert result["material_contract"]["one_click_publish_ready"] is False


@pytest.mark.asyncio
async def test_render_platform_cover_writes_codex_imagegen_request_when_builtin_backend_pending(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            intelligent_copy_cover_image_backend="codex_builtin",
            ffmpeg_timeout_sec=1,
        ),
    )

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    image_generation = metadata["image_generation"]
    request_path = Path(image_generation["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))

    assert metadata["source"] == "reference_cover_fallback"
    assert metadata["publish_ready"] is False
    assert image_generation["status"] == "pending_codex_imagegen"
    assert image_generation["backend"] == "codex_builtin"
    assert request_path.exists()
    assert Path(image_generation["source_image_path"]).exists()
    assert Path(request["output_path"]) == output
    assert image_generation["image_model"] == "codex_builtin_image_generation"
    assert request["image_generation"]["image_model"] == "codex_builtin_image_generation"
    assert request["codex_runner"]["role"] == "codex_exec_agent"
    assert request["codex_runner"]["model"] == "gpt-5.4-mini"
    assert request["codex_runner"]["reasoning_effort"] == "low"
    assert "Codex built-in image_gen" in request["instructions"]
    assert "not as the underlying image model" in request["instructions"]
    assert "concise image-generation brief" in request["instructions"]
    assert request["cover_director_policy"]["codex_role"] == "render_final_cover_with_integrated_typography"
    assert request["cover_director_policy"]["typography_owner"] == "codex_full_cover"
    assert request["cover_director_policy"]["style_profile_key"] == "edc_cinematic_hero_full_cover_v1"
    assert "metal_3d" in request["cover_director_policy"]["headline_effects"]
    assert any(
        "final cover" in item.lower()
        for item in request["cover_director_policy"]["completion_requires"]
    )
    assert any(
        "already contains the requested brand line" in item
        for item in request["cover_director_policy"]["completion_requires"]
    )
    assert request["cover_hard_contract"]["subject_identity_required"] is True
    assert request["cover_hard_contract"]["brand_model_title_required"] is True
    assert request["cover_hard_contract"]["post_title_overlay_required"] is False
    assert request["cover_hard_contract"]["full_bitmap_cover_required"] is True
    assert "fit" in calls
    assert output.exists()
    assert "Codex" in metadata["blocking_reasons"][0]


def test_codex_imagegen_request_completed_requires_bridge_generation_marker(tmp_path: Path) -> None:
    request_path = tmp_path / "cover.codex-imagegen.json"
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"fallback")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(output),
                "prompt": "prompt",
                "cover_hard_contract": {},
                "cover_director_policy": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert imagegen._codex_imagegen_request_completed(
        request_path,
        output,
        expected_prompt="prompt",
        expected_hard_contract={},
        expected_director_policy={},
    ) is False


@pytest.mark.asyncio
async def test_render_platform_cover_writes_completed_snapshot_for_minimax_overlay_flow(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "bilibili-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            intelligent_copy_cover_image_backend="minimax_images_api",
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        return {
            "backend": "minimax_images_api",
            "status": "completed",
            "output_path": str(kwargs["output_path"]),
            "size": "1536x1024",
        }

    def fake_fit_image_to_canvas(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_verify_unexpected_text(**kwargs):
        calls["unexpected"] = kwargs["output_path"]
        return {"unexpected_bitmap_text_detected": False, "detected_text": [], "reason": ""}

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_verify_generated_cover_has_unexpected_bitmap_text", fake_verify_unexpected_text)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda *_args, **_kwargs: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(output),
            "target_size": {"width": 1280, "height": 720},
            "image_dimensions": {"width": 1280, "height": 720},
        },
    )

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4 开箱",
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_brief={
            "product_identity": "MAXACE美杜莎4 EDC折刀",
            "selling_angle": "到手开箱看质感和做工",
            "visual_brief": "刀身特写，标题后期统一叠加。",
            "video_type": "开箱",
        },
    )

    request_payload = json.loads(output.with_suffix(".codex-imagegen.json").read_text(encoding="utf-8"))

    assert metadata["source"] == "image_generation"
    assert metadata["publish_ready"] is True
    assert request_payload["status"] == "completed"
    assert request_payload["backend"] == "minimax_images_api"
    assert request_payload["cover_director_policy"]["typography_owner"] == "local_post_overlay"
    assert request_payload["cover_hard_contract"]["post_title_overlay_required"] is True
    assert request_payload["cover_hard_contract"]["full_bitmap_cover_required"] is False
    assert request_payload["post_title_overlay_applied"] is True
    assert "overlay" in calls


@pytest.mark.asyncio
async def test_render_platform_cover_reference_fallback_is_not_publishable_final_cover(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            intelligent_copy_cover_image_backend="codex_builtin",
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        raise imagegen.CodexImageGenerationPending({"backend": "codex_builtin", "status": "pending_codex_imagegen"})

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_materialize_cover_reference_fallback", lambda **_kwargs: True)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE 美杜莎4 开箱",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert metadata["source"] == "reference_cover_fallback"
    assert metadata["publish_ready"] is False
    assert "封面图像生成未完成" in metadata["blocking_reasons"][0]


@pytest.mark.asyncio
async def test_render_platform_cover_preserves_completed_codex_output(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    output.write_bytes(b"completed cover")
    request_path = tmp_path / "douyin-cover.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "created_at": "2026-05-20T00:00:00+00:00",
                "source_image_path": str(source),
                "output_path": str(output),
                "target_size": {"width": 1080, "height": 1920},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}
    settings = SimpleNamespace(
        intelligent_copy_cover_image_generation_enabled=True,
        intelligent_copy_cover_image_backend="codex_builtin",
        ffmpeg_timeout_sec=1,
    )

    monkeypatch.setattr(ic, "get_settings", lambda: settings)
    monkeypatch.setattr(imagegen, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda metadata, request, path: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(path),
        },
    )

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=None,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert output.exists()
    assert output.read_bytes() == b"completed cover"
    assert metadata["source"] == "image_generation"
    assert metadata["publish_ready"] is True
    assert metadata["image_generation"]["status"] == "completed"
    assert "fit" in calls
    assert calls["fit"]["output_path"] == output
    assert calls["fit"]["fit_mode"] == "cover"
    assert "overlay" in calls


@pytest.mark.asyncio
async def test_apply_platform_cover_title_overlay_promotes_edc_to_battle_style(tmp_path, monkeypatch) -> None:
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"cover")
    calls: list[tuple[str, str]] = []

    async def fake_overlay_title_layout(path, title_lines, cover_style, title_style):
        calls.append((cover_style, title_style))

    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    await ic._apply_platform_cover_title_overlay(
        output_path=output,
        title="MAXACE 美杜莎4双版开箱对比",
        rules={
            "cover_style": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
            "title_style": "comic_boom",
        },
    )

    assert calls == [(ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO, "account_metal_cyber_stack")]


def test_resolve_overlay_title_style_prefers_cover_brief_style_key_for_edc() -> None:
    cover_style, title_style = ic._resolve_overlay_title_style(
        rules={
            "cover_style": "tech_showcase",
            "title_style": "preset_default",
        },
        cover_brief={
            "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        },
    )

    assert cover_style == ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO
    assert title_style == "account_metal_cyber_stack"


def test_resolve_cover_source_full_frame_review_numbers_keeps_four_candidates() -> None:
    review_numbers = ic._resolve_cover_source_full_frame_review_numbers(
        ranked_numbers=[4, 8, 9, 10],
        finalist_numbers=[4, 8, 9, 10],
    )

    assert review_numbers == [4, 8, 9, 10]


def test_resolve_cover_source_candidate_count_normalizes_to_supported_contact_sheet_sizes() -> None:
    assert ic._resolve_cover_source_candidate_count(1) == 4
    assert ic._resolve_cover_source_candidate_count(4) == 4
    assert ic._resolve_cover_source_candidate_count(6) == 9
    assert ic._resolve_cover_source_candidate_count(10) == 9


def test_build_codex_platform_cover_image_prompt_strengthens_portrait_compare_composition() -> None:
    spec = ic._build_platform_cover_prompt_spec(
        title="MAXACE 美杜莎4 对比",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
        cover_brief={
            "product_identity": "美杜莎4 顶配vs次顶配",
            "selling_angle": "双版本完整对比展示，做工和细节表现",
            "visual_brief": "突出真实主体、产品质感和开箱/展示高光，封面标题保持大而清晰。",
            "video_type": "开箱体验",
        },
    )

    prompt = ic._build_codex_platform_cover_image_prompt(spec=spec)

    assert "不要凭空增加第二主体" in prompt
    assert "画面中部要保留主主体展示通道" in prompt
    assert "双主体编辑预算必须极小" not in prompt


@pytest.mark.asyncio
async def test_codex_imagegen_requires_completion_marker_before_publishable_result(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
        ),
    )

    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    output.write_bytes(b"generated")
    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    imagegen.mark_codex_imagegen_request_completed(request_path=request_path, output_path=output)
    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        final_output_path=output,
        request_path=request_path,
        prompt="生成封面",
        width=1280,
        height=720,
    )

    assert metadata["status"] == "completed"
    assert metadata["backend"] == "codex_builtin"
    assert metadata["image_model"] == "codex_builtin_image_generation"
    assert metadata["codex_runner"]["model"] == "gpt-5.4-mini"
    assert metadata["codex_runner"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_codex_imagegen_request_persists_reference_image_pack(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    extra = tmp_path / "extra.jpg"
    extra.write_bytes(b"extra")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
        ),
    )
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "")

    with pytest.raises(imagegen.CodexImageGenerationPending) as exc_info:
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            reference_image_paths=[source, extra],
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    metadata = exc_info.value.metadata
    payload = json.loads(request_path.read_text(encoding="utf-8"))

    assert len(payload["reference_image_paths"]) == 2
    assert Path(payload["source_image_path"]).exists()
    assert all(Path(path).exists() for path in payload["reference_image_paths"])
    assert payload["reference_image_paths"][0] == payload["source_image_path"]
    assert len({Path(path).name for path in payload["reference_image_paths"]}) == 2
    assert metadata["reference_image_paths"] == payload["reference_image_paths"]


@pytest.mark.asyncio
async def test_codex_imagegen_request_reuses_shared_highlight_reference_pack_without_per_group_copies(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    cover_dir = material_dir / "_cover"
    cover_dir.mkdir(parents=True)
    source = cover_dir / "00-highlight-reference-1.jpg"
    extra = cover_dir / "00-highlight-reference-2.jpg"
    source.write_bytes(b"source")
    extra.write_bytes(b"extra")
    output = cover_dir / "00-cover-landscape_16_9.jpg"
    request_path = cover_dir / "00-cover-landscape_16_9.codex-imagegen.json"

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
        ),
    )
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "")

    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            reference_image_paths=[source, extra],
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    payload = json.loads(request_path.read_text(encoding="utf-8"))

    assert payload["source_image_path"] == str(source)
    assert payload["reference_image_paths"] == [str(source), str(extra)]
    assert not (cover_dir / "00-cover-landscape_16_9.codex-imagegen-reference.jpg").exists()
    assert not (cover_dir / "00-cover-landscape_16_9.codex-imagegen-reference-2.jpg").exists()


@pytest.mark.asyncio
async def test_codex_imagegen_completed_request_invalidates_when_prompt_changes(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    output.write_bytes(b"generated")
    request_path = tmp_path / "cover.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "created_at": "2026-05-20T00:00:00+00:00",
                "source_image_path": str(source),
                "output_path": str(output),
                "prompt": "旧 prompt",
                "cover_hard_contract": {"required_title_lines": {"main": "旧标题"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
        ),
    )
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "")

    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="新 prompt",
            width=1280,
            height=720,
            hard_contract={"required_title_lines": {"main": "新标题"}},
        )

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pending_codex_imagegen"
    assert payload["prompt"] == "新 prompt"
    assert payload["cover_hard_contract"]["required_title_lines"]["main"] == "新标题"


@pytest.mark.asyncio
async def test_codex_imagegen_can_autocomplete_through_host_bridge(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"
    calls: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            output.write_bytes(b"generated")
            payload = json.loads(request_path.read_text(encoding="utf-8"))
            payload["status"] = "completed"
            request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return {"status": "completed", "output_path": str(output)}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            calls["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json=None, headers=None):
            calls["url"] = url
            calls["json"] = json
            calls["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "bridge-token")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "http://bridge/v1/host/complete-codex-imagegen")
    monkeypatch.setattr(imagegen, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
            intelligent_copy_cover_image_timeout_sec=90,
        ),
    )

    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        final_output_path=output,
        request_path=request_path,
        prompt="生成封面",
        width=1280,
        height=720,
    )

    assert output.exists()
    assert metadata["status"] == "completed"
    assert metadata["backend"] == "codex_builtin"
    assert calls["url"] == "http://bridge/v1/host/complete-codex-imagegen"
    assert calls["headers"]["Authorization"] == "Bearer bridge-token"
    assert calls["json"]["request_path"] == str(request_path)
    assert calls["json"]["model"] == "gpt-5.4-mini"
    assert calls["json"]["timeout_sec"] == 90
    assert calls["timeout"] == 110


@pytest.mark.asyncio
async def test_codex_imagegen_bridge_failure_stays_pending_with_recorded_error(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json=None, headers=None):
            raise RuntimeError("Server error '502 Bad Gateway' for url 'http://bridge/v1/host/complete-codex-imagegen'")

    monkeypatch.setattr(imagegen, "resolve_codex_proxy_token", lambda: "bridge-token")
    monkeypatch.setattr(imagegen, "resolve_codex_proxy_sibling_url", lambda _path: "http://bridge/v1/host/complete-codex-imagegen")
    monkeypatch.setattr(imagegen, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
            intelligent_copy_cover_image_timeout_sec=90,
        ),
    )

    with pytest.raises(imagegen.CodexImageGenerationPending) as exc_info:
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    assert "502 Bad Gateway" in exc_info.value.metadata["auto_completion_error"]
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert "502 Bad Gateway" in request_payload["auto_completion_error"]


@pytest.mark.asyncio
async def test_minimax_image_backend_edits_cover_with_same_prompt_shape(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source-image")
    output = tmp_path / "cover.jpg"
    calls: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "id": "mini-job-1",
                "base_resp": {"status_code": 0, "status_msg": "ok"},
                "data": {"images_base64": [base64.b64encode(b"minimax-cover").decode("ascii")]},
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            calls["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers=None, json=None):
            calls["url"] = url
            calls["headers"] = headers
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setattr(imagegen, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="minimax_images_api",
            intelligent_copy_cover_image_model="image2",
            intelligent_copy_cover_image_timeout_sec=45,
            minimax_api_key="mini-secret",
            minimax_base_url="https://api.minimaxi.com/v1",
        ),
    )

    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        prompt="生成封面",
        width=1080,
        height=1920,
    )

    assert output.exists()
    assert output.read_bytes() == b"minimax-cover"
    assert metadata["backend"] == "minimax_images_api"
    assert metadata["model"] == "image-01"
    assert metadata["aspect_ratio"] == "9:16"
    assert metadata["request_id"] == "mini-job-1"
    assert calls["url"] == "https://api.minimaxi.com/v1/image_generation"
    assert calls["headers"]["Authorization"] == "Bearer mini-secret"
    assert calls["json"]["prompt"] == "生成封面"
    assert calls["json"]["width"] == 1080
    assert calls["json"]["height"] == 1920
    assert calls["json"]["prompt_optimizer"] is False
    assert calls["json"]["subject_reference"][0]["type"] == "character"
    assert calls["json"]["subject_reference"][0]["image_file"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_generate_intelligent_copy_passes_selected_platforms_to_packaging(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(source_dir / "smart-copy"),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    calls: dict[str, object] = {}

    async def fake_generate_platform_packaging(**kwargs):
        calls["target_platforms"] = kwargs.get("target_platforms")
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "douyin": {
                    "titles": ["MAXACE美杜莎4到货了"],
                    "description": "MAXACE美杜莎4到货了，顶配和次顶配一起看。",
                    "tags": ["MAXACE", "美杜莎4"],
                },
                "x": {
                    "titles": [],
                    "description": "this should be ignored",
                    "tags": ["ignored"],
                },
            },
        }

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    async def fake_render_cover_group(**_kwargs):
        output_path = Path(_kwargs["output_path"])
        output_path.write_bytes(b"cover")
        return {"publish_ready": True, "blocking_reasons": []}

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "save_platform_packaging_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)

    result = await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin"])

    assert calls["target_platforms"] == ["douyin"]
    assert [item["key"] for item in result["platforms"]] == ["douyin"]


@pytest.mark.asyncio
async def test_generate_intelligent_copy_blocks_fallback_packaging_from_formal_output(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(source_dir / "smart-copy"),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    async def fake_generate_platform_packaging(**_kwargs):
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "generation_repair_trace": [{"status": "deterministic_fallback", "reason": "llm timeout"}],
            "platforms": {
                "douyin": {
                    "titles": ["MAXACE美杜莎4到货了"],
                    "description": "MAXACE美杜莎4到货了，顶配和次顶配一起看。",
                    "tags": ["MAXACE", "美杜莎4"],
                },
            },
        }

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
            "strategy_source": "llm",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(
        ic,
        "save_platform_packaging_markdown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should block before writing markdown")),
    )
    monkeypatch.setattr(
        ic,
        "_render_or_reuse_platform_cover_group",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should block before rendering cover")),
    )
    monkeypatch.setattr(
        ic,
        "_write_platform_material_files",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should block before writing platform files")),
    )

    result = await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin"])

    assert result["status"] == "blocked"
    assert result["platforms"] == []
    assert result["publish_ready"] is False
    assert "platform_packaging_deterministic_fallback" in result["blocking_reasons"]
    assert not (source_dir / "smart-copy" / "platform-packaging.md").exists()
    assert not (source_dir / "smart-copy" / "smart-copy.json").exists()


@pytest.mark.asyncio
async def test_generate_intelligent_copy_blocks_fallback_cover_brief_from_formal_output(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(source_dir / "smart-copy"),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    async def fake_generate_platform_packaging(**_kwargs):
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "douyin": {
                    "titles": ["MAXACE美杜莎4到货了"],
                    "description": "MAXACE美杜莎4到货了，顶配和次顶配一起看。",
                    "tags": ["MAXACE", "美杜莎4"],
                },
            },
        }

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
            "strategy_source": "fallback",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(
        ic,
        "save_platform_packaging_markdown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should block before writing markdown")),
    )

    result = await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin"])

    assert result["status"] == "blocked"
    assert result["platforms"] == []
    assert "intelligent_copy_cover_brief_fallback" in result["blocking_reasons"]
    assert not (source_dir / "smart-copy" / "platform-packaging.md").exists()


@pytest.mark.asyncio
async def test_generate_intelligent_copy_drains_pending_cover_group_requests(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(source_dir / "smart-copy"),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    async def fake_generate_platform_packaging(**_kwargs):
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "douyin": {
                    "titles": ["MAXACE美杜莎4到货了", "顶配次顶配怎么选", "差别都在细节"],
                    "description": "MAXACE美杜莎4到货了，上手先看顶配和次顶配的细节差别。",
                    "tags": ["MAXACE", "美杜莎4"],
                },
            },
        }

    async def fake_render_cover_group(**_kwargs):
        output_path = Path(_kwargs["output_path"])
        output_path.write_bytes(b"fallback")
        return {
            "publish_ready": False,
            "blocking_reasons": ["封面等待 Codex 内置 imagegen 执行完成，已回退使用参考帧封面"],
            "image_generation": {
                "status": "pending_codex_imagegen",
                "request_path": str(output_path.with_suffix(".codex-imagegen.json")),
                "output_path": str(output_path),
            },
        }

    calls: dict[str, object] = {}

    async def fake_drain_pending_cover_group_requests(*, cache, material_dir):
        calls["drain_cache_size"] = len(cache)
        calls["drain_material_dir"] = str(material_dir)

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "save_platform_packaging_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)
    monkeypatch.setattr(ic, "_drain_pending_cover_group_requests", fake_drain_pending_cover_group_requests)

    await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin"])

    assert calls["drain_cache_size"] >= 1
    assert calls["drain_material_dir"] == str(source_dir / "smart-copy")


@pytest.mark.asyncio
async def test_generate_intelligent_copy_reuses_complete_platform_materials_and_only_fills_gaps(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "douyin",
                        "label": "抖音",
                        "has_title": True,
                        "body_label": "简介",
                        "tag_label": "标签",
                        "titles": ["MAXACE美杜莎4到货了", "MAXACE美杜莎4双档开箱", "MAXACE美杜莎4怎么选"],
                        "primary_title": "MAXACE美杜莎4到货了",
                        "title_copy_all": "1. MAXACE美杜莎4到货了",
                        "body": "MAXACE美杜莎4到货了，上手先看顶配和次顶配的细节差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "MAXACE美杜莎4到货了\n\nMAXACE美杜莎4到货了，上手先看顶配和次顶配的细节差别。\n\n#MAXACE #美杜莎4",
                    },
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "body_label": "正文",
                        "tag_label": "话题",
                        "titles": ["旧稿"],
                        "primary_title": "旧稿",
                        "body": "",
                        "tags": [],
                        "tags_copy": "",
                        "full_copy": "",
                    },
                ],
                "highlights": {"product": "MAXACE 美杜莎4"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})
    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        }

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "save_platform_packaging_markdown", lambda *_args, **_kwargs: None)

    async def fake_prepare_cover_source(**_kwargs):
        return None

    async def fake_render_cover_group(**_kwargs):
        return {"publish_ready": True, "blocking_reasons": []}

    calls: dict[str, object] = {}

    async def fake_generate_platform_packaging(**kwargs):
        calls["target_platforms"] = kwargs.get("target_platforms")
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "xiaohongshu": {
                    "titles": ["美杜莎4两档到手", "美杜莎4顶配次顶配对比", "MAXACE美杜莎4细节看这里"],
                    "description": "MAXACE美杜莎4两个配置一起到手，先看上手和细节差别。",
                    "tags": ["MAXACE", "美杜莎4", "开箱"],
                }
            },
        }

    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)
    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)

    result = await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin", "xiaohongshu"])

    assert calls["target_platforms"] == ["xiaohongshu"]
    materials = {item["key"]: item for item in result["platforms"]}
    assert set(materials.keys()) == {"douyin", "xiaohongshu"}
    assert materials["douyin"]["body"] == "MAXACE美杜莎4到货了，上手先看顶配和次顶配的细节差别。"
    assert materials["xiaohongshu"]["body"] == "MAXACE美杜莎4两个配置一起到手，先看上手和细节差别。"


@pytest.mark.asyncio
async def test_generate_intelligent_copy_skips_rewriting_existing_files_for_reused_material(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    for name in ("02-douyin-titles.txt", "02-douyin-body.txt", "02-douyin-tags.txt", "02-douyin.md"):
        (material_dir / name).write_text("existing\n", encoding="utf-8")
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "douyin",
                        "label": "抖音",
                        "has_title": True,
                        "body_label": "描述",
                        "tag_label": "标签",
                        "titles": ["MAXACE美杜莎4到货了", "顶配次顶配怎么选", "差别都在细节"],
                        "primary_title": "MAXACE美杜莎4到货了",
                        "title_copy_all": "1. MAXACE美杜莎4到货了",
                        "body": "MAXACE美杜莎4到货了，上手看顶配和次顶配的差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "MAXACE美杜莎4到货了\n\nMAXACE美杜莎4到货了，上手看顶配和次顶配的差别。\n\n#MAXACE #美杜莎4",
                        "publish_ready": False,
                        "blocking_reasons": ["封面图像生成未完成"],
                    },
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "body_label": "正文",
                        "tag_label": "话题",
                        "titles": ["旧稿"],
                        "primary_title": "旧稿",
                        "body": "",
                        "tags": [],
                        "tags_copy": "",
                        "full_copy": "",
                    },
                ],
                "highlights": {"product": "MAXACE 美杜莎4"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    async def fake_render_cover_group(**_kwargs):
        return {"publish_ready": True, "blocking_reasons": []}

    async def fake_generate_platform_packaging(**kwargs):
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "xiaohongshu": {
                    "titles": ["美杜莎4两档到手", "美杜莎4顶配次顶配对比", "MAXACE美杜莎4细节看这里"],
                    "description": "MAXACE美杜莎4两个配置一起到手，先看上手和细节差别。",
                    "tags": ["MAXACE", "美杜莎4", "开箱"],
                }
            },
        }

    written_keys: list[str] = []

    def fake_write_platform_material_files(*, material_dir, index, material):
        written_keys.append(str(material.get("key") or ""))

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "save_platform_packaging_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", fake_write_platform_material_files)
    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)

    await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin", "xiaohongshu"])

    assert written_keys == ["xiaohongshu"]
    assert smart_copy_material_json_path(material_dir).exists()
    assert not (material_dir / "smart-copy.json").exists()
    assert smart_copy_platform_titles_path(material_dir, 2, "douyin").exists()
    assert smart_copy_platform_body_path(material_dir, 2, "douyin").exists()
    assert smart_copy_platform_tags_path(material_dir, 2, "douyin").exists()
    assert not (material_dir / "02-douyin-titles.txt").exists()
    assert not (material_dir / "02-douyin-body.txt").exists()
    assert not (material_dir / "02-douyin-tags.txt").exists()
    assert (material_dir / "02-douyin.md").exists()


@pytest.mark.asyncio
async def test_rerender_existing_cover_groups_restores_packaging_context_from_sibling_files(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "copy_style": "attention_grabbing",
                "content_profile_summary": {
                    "subject_brand": "MAXACE",
                    "subject_model": "美杜莎4",
                    "subject_type": "EDC折刀",
                    "summary": "双版本开箱对比。",
                },
                "platforms": [
                    {
                        "key": "douyin",
                        "label": "抖音",
                        "has_title": True,
                        "body_label": "描述",
                        "tag_label": "标签",
                        "titles": ["MAXACE美杜莎4到货了"],
                        "primary_title": "MAXACE美杜莎4到货了",
                        "body": "MAXACE美杜莎4到货了。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "MAXACE美杜莎4到货了",
                    }
                ],
                "highlights": {"product": "this should not win"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "highlights": {"product": "MAXACE 美杜莎4 顶配次顶配"},
                "fact_sheet": {"marker": "from-platform-packaging"},
                "platforms": {
                    "douyin": {
                        "titles": ["MAXACE美杜莎4顶配次顶配开箱"],
                        "description": "双版本一起看。",
                        "tags": ["MAXACE", "美杜莎4", "开箱"],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    seen: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])

    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", lambda **_kwargs: asyncio.sleep(0, result=None))
    monkeypatch.setattr(ic, "_load_cover_source_manifest", lambda _path: {"source": "llm_full_frame_review"})

    def fake_build_copy_brief(**kwargs):
        seen["copy_brief_subject"] = kwargs["content_profile"].get("subject_model")
        return {"topic_subject": "MAXACE 美杜莎4"}

    async def fake_build_cover_brief(**kwargs):
        seen["packaging_highlights"] = kwargs["packaging"].get("highlights")
        seen["packaging_fact_sheet"] = kwargs["packaging"].get("fact_sheet")
        seen["content_profile"] = dict(kwargs["content_profile"])
        return {
            "cover_title": "MAXACE美杜莎4",
            "video_type": "开箱对比",
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本同框",
            "visual_brief": "主体真实，双刀同框。",
        }

    async def fake_render_cover_group(**kwargs):
        output_path = Path(kwargs["output_path"])
        output_path.write_bytes(b"cover")
        seen["render_title"] = kwargs["title"]
        return {"publish_ready": True, "blocking_reasons": []}

    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", fake_build_copy_brief)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)

    result = await ic.rerender_existing_intelligent_copy_cover_groups(
        str(source_dir),
        platforms=["douyin"],
        creator_profile_name="FAS",
    )

    assert seen["copy_brief_subject"] == "美杜莎4"
    assert seen["packaging_highlights"] == {"product": "MAXACE 美杜莎4 顶配次顶配"}
    assert seen["packaging_fact_sheet"] == {"marker": "from-platform-packaging"}
    assert seen["content_profile"]["subject_brand"] == "MAXACE"
    assert seen["render_title"] == "MAXACE美杜莎4"
    assert result["platforms"][0]["key"] == "douyin"
    assert result["cover_brief"]["cover_title"] == "MAXACE美杜莎4"
    assert result["creator_profile_name"] == "FAS"
    assert result["publication_context"]["creator_profile_name"] == "FAS"


@pytest.mark.asyncio
async def test_restore_existing_cover_generation_context_reuses_verified_source_by_default(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    cover_source_path = material_dir / "00-highlight-cover-source.jpg"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    cover_source_path.write_bytes(b"stale-cover-source")
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "copy_style": "attention_grabbing",
                "cover_source_path": str(cover_source_path),
                "cover_source_manifest": {
                    "source": "llm_full_frame_review_valid_backup",
                    "candidate_index": 7,
                    "seek_sec": 449.97,
                },
                "content_profile_summary": {
                    "subject_brand": "MAXACE",
                    "subject_model": "美杜莎4",
                    "subject_type": "EDC折刀",
                },
                "platforms": [{"key": "douyin", "titles": ["MAXACE美杜莎4到货了"], "body": "body", "tags": ["MAXACE"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "platform-packaging.json").write_text(
        json.dumps({"highlights": {"product": "MAXACE 美杜莎4"}, "platforms": {"douyin": {}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})

    extracted: list[tuple[Path, float]] = []

    async def fake_extract_frame(_video_path, output_path, seek_sec):
        extracted.append((Path(output_path), float(seek_sec)))
        Path(output_path).write_bytes(b"restored-cover-source")

    async def fail_prepare_cover_source(**_kwargs):
        raise AssertionError("should reuse existing verified cover source instead of rerunning source selection")

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4",
            "video_type": "开箱对比",
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本同框",
            "visual_brief": "主体真实，双刀同框。",
        }

    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fail_prepare_cover_source)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    context = await ic._restore_existing_intelligent_cover_generation_context(str(source_dir), platforms=["douyin"])

    assert context["cover_source"] == cover_source_path.resolve()
    assert context["cover_source_manifest"]["source"] == "llm_full_frame_review_valid_backup"
    assert extracted == [(cover_source_path.resolve(), 449.97)] or extracted == [(cover_source_path, 449.97)]


@pytest.mark.asyncio
async def test_restore_existing_cover_generation_context_reuses_persisted_cover_brief(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path = source_dir / "video.mp4"
    subtitle_path = source_dir / "video.srt"
    cover_source_path = material_dir / "00-highlight-cover-source.jpg"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    cover_source_path.write_bytes(b"cover-source")
    (material_dir / "00-highlight-cover-source.json").write_text(
        json.dumps({"source": "llm_full_frame_review_valid_backup", "seek_sec": 449.97}, ensure_ascii=False),
        encoding="utf-8",
    )
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "cover_brief": {
                    "cover_title": "MAXACE美杜莎4双版开箱",
                    "video_type": "开箱体验",
                    "product_identity": "MAXACE 美杜莎4 EDC折刀（顶配与高配镜面双版本）",
                    "selling_angle": "两版本完整对比",
                    "visual_brief": "双主体同框，突出金属质感",
                    "background_strategy": "preserve_reference_background",
                },
                "cover_source_path": str(cover_source_path),
                "cover_source_manifest": {"source": "llm_full_frame_review_valid_backup", "seek_sec": 449.97},
                "content_profile_summary": {
                    "subject_brand": "MAXACE",
                    "subject_model": "美杜莎4",
                    "subject_type": "EDC折刀",
                },
                "platforms": [{"key": "xiaohongshu", "titles": ["MAXACE美杜莎4"], "body": "body", "tags": ["MAXACE"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "platform-packaging.json").write_text(
        json.dumps({"highlights": {"product": "MAXACE 美杜莎4"}, "platforms": {"xiaohongshu": {}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})
    async def fake_extract_frame(_video_path, output_path, _seek):
        Path(output_path).write_bytes(b"restored")

    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    async def fail_build_cover_brief(**_kwargs):
        raise AssertionError("should reuse persisted cover_brief instead of rerunning LLM cover planning")

    async def fail_prepare_cover_source(**_kwargs):
        raise AssertionError("should reuse existing verified cover source instead of rerunning source selection")

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fail_build_cover_brief)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fail_prepare_cover_source)

    context = await ic._restore_existing_intelligent_cover_generation_context(str(source_dir), platforms=["xiaohongshu"])

    assert context["cover_brief"]["cover_title"] == "MAXACE美杜莎4双版开箱"
    assert context["cover_brief"]["strategy_axes"]["content_scheme"]["key"] == "unboxing_single_subject_v1"


@pytest.mark.asyncio
async def test_resolve_restored_cover_brief_tolerates_missing_existing_result(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    async def fake_build_cover_brief(**kwargs):
        captured.update(kwargs)
        return {
            "cover_title": "MAXACE美杜莎4双版开箱",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "双主体同框，突出金属质感",
        }

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)

    brief = await ic._resolve_restored_cover_brief(
        None,
        video_path=tmp_path / "video.mp4",
        subtitle_items=[{"text_final": "MAXACE 美杜莎4 到货了"}],
        content_profile={"subject_model": "美杜莎4", "subject_type": "EDC折刀"},
        copy_brief={"topic_subject": "MAXACE 美杜莎4"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4"}},
    )

    assert brief["cover_title"] == "MAXACE美杜莎4双版开箱"
    assert captured["packaging"] == {"highlights": {"product": "MAXACE 美杜莎4"}}


@pytest.mark.asyncio
async def test_resolve_restored_cover_brief_rebuilds_persisted_fallback_payload(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}

    async def fake_build_cover_brief(**_kwargs):
        calls["count"] += 1
        return {
            "cover_title": "MAXACE美杜莎4双版开箱",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "双主体同框，突出金属质感",
            "strategy_source": "llm",
        }

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)

    brief = await ic._resolve_restored_cover_brief(
        {
            "cover_brief": {
                "cover_title": "兜底封面标题",
                "product_identity": "MAXACE 美杜莎4",
                "selling_angle": "兜底卖点",
                "visual_brief": "兜底视觉描述",
                "strategy_source": "fallback",
            }
        },
        video_path=tmp_path / "video.mp4",
        subtitle_items=[{"text_final": "MAXACE 美杜莎4 到货了"}],
        content_profile={"subject_model": "美杜莎4", "subject_type": "EDC折刀"},
        copy_brief={"topic_subject": "MAXACE 美杜莎4"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4"}},
    )

    assert calls["count"] == 1
    assert brief["cover_title"] == "MAXACE美杜莎4双版开箱"
    assert brief["strategy_source"] == "llm"


@pytest.mark.asyncio
async def test_prepare_cover_source_preserves_existing_verified_source_when_refresh_falls_back(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    existing_source_path = smart_copy_cover_source_image_path(material_dir)
    existing_source_path.parent.mkdir(parents=True, exist_ok=True)
    existing_source_path.write_bytes(b"verified")

    monkeypatch.setattr(ic, "_probe_duration", lambda _path: 600.0)
    monkeypatch.setattr(ic, "_sample_cover_candidates", lambda *_args, **_kwargs: [])

    extracted: list[Path] = []

    async def fake_extract_frame(_video_path, output_path, _seek):
        extracted.append(Path(output_path))
        Path(output_path).write_bytes(b"new")

    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    result = await ic._prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile={"subject_model": "MAXACE 美杜莎4"},
        packaging={"highlights": {"product": "MAXACE 美杜莎4"}},
        existing_verified_source_path=existing_source_path,
        existing_verified_manifest={"source": "llm_full_frame_review_valid_backup", "candidate_index": 7},
    )

    assert result == existing_source_path
    assert extracted == []
    assert existing_source_path.read_bytes() == b"verified"


@pytest.mark.asyncio
async def test_rerender_existing_cover_groups_preserves_unselected_platforms_and_stable_serials(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    source_frame = material_dir / "00-highlight-cover-source.jpg"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")
    source_frame.write_bytes(b"verified-source")
    for name in (
        "01-bilibili-body.txt",
        "01-bilibili-tags.txt",
        "01-bilibili.md",
        "02-xiaohongshu-body.txt",
        "02-xiaohongshu-tags.txt",
        "02-xiaohongshu.md",
        "05-wechat_channels-body.txt",
        "05-wechat_channels-tags.txt",
        "05-wechat_channels.md",
    ):
        (material_dir / name).write_text("existing\n", encoding="utf-8")
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "copy_style": "attention_grabbing",
                "cover_source_path": str(source_frame),
                "cover_source_manifest": {"source": "llm_full_frame_review_valid_backup", "seek_sec": 449.97},
                "content_profile_summary": {
                    "subject_brand": "MAXACE",
                    "subject_model": "美杜莎4",
                    "subject_type": "EDC折刀",
                },
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "body_label": "简介",
                        "tag_label": "标签",
                        "titles": ["B站旧稿"],
                        "primary_title": "B站旧稿",
                        "body": "bilibili body",
                        "tags": ["MAXACE"],
                        "tags_copy": "#MAXACE",
                        "full_copy": "bilibili body",
                    },
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "body_label": "正文",
                        "tag_label": "话题",
                        "titles": ["小红书旧稿"],
                        "primary_title": "小红书旧稿",
                        "body": "xiaohongshu body",
                        "tags": ["美杜莎4"],
                        "tags_copy": "#美杜莎4",
                        "full_copy": "xiaohongshu body",
                    },
                    {
                        "key": "wechat_channels",
                        "label": "视频号",
                        "has_title": True,
                        "body_label": "描述",
                        "tag_label": "标签",
                        "titles": ["视频号旧稿"],
                        "primary_title": "视频号旧稿",
                        "body": "wechat body",
                        "tags": ["MAXACE"],
                        "tags_copy": "#MAXACE",
                        "full_copy": "wechat body",
                        "platform_specific_overrides": {
                            "manual_handoff_only": True,
                            "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "highlights": {"product": "MAXACE 美杜莎4"},
                "platforms": {
                    "bilibili": {"titles": ["B站旧稿"], "description": "bilibili body", "tags": ["MAXACE"]},
                    "xiaohongshu": {"titles": ["小红书旧稿"], "description": "xiaohongshu body", "tags": ["美杜莎4"]},
                    "wechat-channels": {"titles": ["视频号旧稿"], "description": "wechat body", "tags": ["MAXACE"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})
    async def fake_extract_frame(_video_path, output_path, _seek_sec):
        Path(output_path).write_bytes(b"restored-source")
    monkeypatch.setattr(ic, "_extract_frame", fake_extract_frame)

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "MAXACE美杜莎4",
            "video_type": "开箱对比",
            "product_identity": "MAXACE 美杜莎4 顶配与次顶配",
            "selling_angle": "双版本同框",
            "visual_brief": "主体真实，双刀同框。",
        }

    written_serials: list[tuple[int, str]] = []

    def fake_write_platform_material_files(*, material_dir, index, material):
        written_serials.append((index, str(material.get("key") or "")))

    async def fake_render_cover_group(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"cover")
        return {"publish_ready": True, "blocking_reasons": []}

    async def fake_prime_standard_cover_matrix_groups(**kwargs):
        return kwargs["cache"]

    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_write_platform_material_files", fake_write_platform_material_files)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_prime_standard_cover_matrix_groups", fake_prime_standard_cover_matrix_groups)

    result = await ic.rerender_existing_intelligent_copy_cover_groups(str(source_dir), platforms=["xiaohongshu"])

    assert [item["key"] for item in result["platforms"]] == ["bilibili", "xiaohongshu", "wechat-channels"]
    assert written_serials
    assert set(written_serials) == {(2, "xiaohongshu")}
    packaging_payload = json.loads((material_dir / "_meta" / "platform-packaging.json").read_text(encoding="utf-8"))
    assert sorted((packaging_payload.get("platforms") or {}).keys()) == ["bilibili", "wechat-channels", "xiaohongshu"]


def test_refresh_cover_group_cache_status_reloads_completed_request_from_disk(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    output_path = material_dir / "00-cover-landscape_4_3.jpg"
    request_path = material_dir / "00-cover-landscape_4_3.codex-imagegen.json"
    output_path.write_bytes(b"cover")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "output_path": str(output_path),
                "bitmap_title_contract_passed": True,
                "compare_subject_contract_passed": True,
                "cover_director_policy": {
                    "style_profile_key": "fas_edc_signature_full_cover_v1",
                    "subject_fidelity_scheme": {"key": "generic_subject_fidelity_v1"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache = {
        "landscape_4_3": {
            "publish_ready": False,
            "blocking_reasons": ["封面生成元数据仍标记为等待图片生成完成"],
            "warnings": [],
            "image_generation": {
                "request_path": str(request_path),
                "output_path": str(output_path),
            },
            "cover_group": {
                "key": "landscape_4_3",
                "label": "4:3 横版母版",
                "cover_path": str(output_path),
                "members": [],
            },
        }
    }

    ic._refresh_cover_group_cache_status(cache=cache, material_dir=material_dir)

    refreshed = cache["landscape_4_3"]
    assert refreshed["publish_ready"] is True
    assert refreshed["blocking_reasons"] == []


def test_refresh_existing_cover_generation_node_infers_request_path_from_output_when_missing(tmp_path) -> None:
    material_dir = tmp_path
    output_path = material_dir / "00-cover-portrait_9_16.jpg"
    output_path.write_bytes(b"jpg")
    request_path = output_path.with_suffix(".codex-imagegen.json")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(output_path),
                "cover_hard_contract": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generation = {
        "source": "cover_group_reuse",
        "publish_ready": False,
        "blocking_reasons": ["封面等待 Codex 内置 imagegen 执行完成"],
        "image_generation": {
            "backend": "codex_builtin",
            "status": "pending_codex_imagegen",
            "output_path": str(output_path),
        },
    }

    refreshed = ic._refresh_existing_cover_generation_node(
        generation=generation,
        output_path=output_path,
        material_dir=material_dir,
    )

    assert refreshed is not None
    assert refreshed["image_generation"]["request_path"] == str(request_path)
    assert refreshed["image_generation"]["status"] == "completed"


def test_assess_cover_publish_readiness_accepts_trusted_group_derivative_output(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-landscape_16_9.jpg"
    platform_output = material_dir / "01-bilibili-cover.jpg"
    Image.new("RGB", (160, 90), "black").save(group_output)
    time.sleep(1.1)
    Image.new("RGB", (160, 90), "white").save(platform_output)
    request_payload = {
        "status": "completed",
        "backend": "codex_builtin",
        "created_at": "2026-06-03T10:00:00+08:00",
        "output_path": str(group_output),
        "target_size": {"width": 160, "height": 90},
    }
    cover_generation = {
        "source": "cover_group_reuse",
        "cover_group": {
            "key": "landscape_16_9",
            "cover_path": str(group_output),
            "members": ["bilibili"],
        },
        "group_generation": {
            "image_generation": {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(group_output),
            }
        },
        "image_generation": {
            "status": "completed",
            "backend": "codex_builtin",
            "output_path": str(group_output),
        },
    }

    assessment = ic.assess_cover_publish_readiness(
        cover_generation,
        request_payload,
        platform_output,
    )

    assert assessment["publish_ready"] is True
    assert assessment["blocking_reasons"] == []


def test_refresh_existing_cover_generation_node_uses_cover_group_lineage_for_platform_derivative(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-landscape_16_9.jpg"
    platform_output = material_dir / "01-bilibili-cover.jpg"
    Image.new("RGB", (160, 90), "black").save(group_output)
    time.sleep(1.1)
    Image.new("RGB", (160, 90), "white").save(platform_output)
    request_path = group_output.with_suffix(".codex-imagegen.json")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "created_at": "2026-06-03T10:00:00+08:00",
                "output_path": str(group_output),
                "target_size": {"width": 160, "height": 90},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generation = {
        "source": "cover_group_reuse",
        "cover_group": {
            "key": "landscape_16_9",
            "cover_path": str(group_output),
            "members": ["bilibili"],
        },
        "group_generation": {
            "image_generation": {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(group_output),
                "request_path": str(request_path),
            }
        },
        "image_generation": {
            "status": "completed",
            "backend": "codex_builtin",
            "output_path": str(group_output),
            "request_path": str(request_path),
        },
    }

    refreshed = ic._refresh_existing_cover_generation_node(
        generation=generation,
        output_path=platform_output,
        material_dir=material_dir,
    )

    assert refreshed is not None
    assert refreshed["publish_ready"] is True
    assert refreshed["blocking_reasons"] == []


def test_refresh_existing_cover_generation_node_keeps_reference_cover_fallback_blocked(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-landscape_16_9.jpg"
    platform_output = material_dir / "01-bilibili-cover.jpg"
    Image.new("RGB", (160, 90), "black").save(group_output)
    Image.new("RGB", (160, 90), "black").save(platform_output)
    request_path = group_output.with_suffix(".codex-imagegen.json")
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "created_at": "2026-06-03T10:00:00+08:00",
                "output_path": str(group_output),
                "target_size": {"width": 160, "height": 90},
                "bitmap_title_contract_verified_at": "2026-06-03T10:00:03+08:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generation = {
        "source": "cover_group_reuse",
        "cover_group": {
            "key": "landscape_16_9",
            "cover_path": str(group_output),
            "members": ["bilibili"],
        },
        "group_generation": {
            "source": "reference_cover_fallback",
            "image_generation": {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "output_path": str(group_output),
                "request_path": str(request_path),
            },
        },
        "image_generation": {
            "status": "pending_codex_imagegen",
            "backend": "codex_builtin",
            "output_path": str(group_output),
            "request_path": str(request_path),
        },
    }

    refreshed = ic._refresh_existing_cover_generation_node(
        generation=generation,
        output_path=platform_output,
        material_dir=material_dir,
    )

    assert refreshed is not None
    assert refreshed["publish_ready"] is False
    assert "封面当前仅为参考帧占位图，正式生图尚未完成" in refreshed["blocking_reasons"]


def test_refresh_cover_group_reuse_platform_derivative_recopies_stale_platform_cover(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-landscape_16_9.jpg"
    platform_output = material_dir / "01-bilibili-cover.jpg"
    Image.new("RGB", (160, 90), "black").save(platform_output)
    time.sleep(1.1)
    Image.new("RGB", (160, 90), "white").save(group_output)
    old_mtime = platform_output.stat().st_mtime
    material = {
        "key": "bilibili",
        "cover_path": str(platform_output),
        "cover_generation": {
            "source": "cover_group_reuse",
            "cover_group": {
                "key": "landscape_16_9",
                "label": "16:9 横版母版",
                "cover_path": str(group_output),
                "members": ["bilibili"],
            },
            "group_generation": {
                "publish_ready": True,
                "blocking_reasons": [],
                "warnings": [],
                "image_generation": {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "output_path": str(group_output),
                    "request_path": str(group_output.with_suffix(".codex-imagegen.json")),
                },
            },
        },
    }

    ic._refresh_cover_group_reuse_platform_derivative(
        material=material,
        material_dir=material_dir,
        rules={"cover_size": (160, 90)},
    )

    assert platform_output.stat().st_mtime > old_mtime
    refreshed_generation = material["cover_generation"]
    assert refreshed_generation["source"] == "cover_group_reuse"
    assessment = ic.assess_cover_publish_readiness(
        refreshed_generation,
        {"status": "completed", "backend": "codex_builtin", "output_path": str(group_output), "target_size": {"width": 160, "height": 90}},
        platform_output,
    )
    assert assessment["publish_ready"] is True


def test_resolve_cover_verification_bitmap_path_uses_final_bitmap_for_codex_full_cover(tmp_path) -> None:
    output_path = tmp_path / "final.jpg"
    pre_overlay_path = tmp_path / "pre-overlay.jpg"
    output_path.write_bytes(b"final")
    pre_overlay_path.write_bytes(b"pre")

    resolved = ic._resolve_cover_verification_bitmap_path(
        request_payload={
            "pre_overlay_output_path": str(pre_overlay_path),
            "cover_director_policy": {"typography_owner": "codex_full_cover"},
        },
        output_path=output_path,
    )

    assert resolved == output_path


@pytest.mark.asyncio
async def test_revalidate_existing_cover_generation_request_rewrites_stale_failed_verdicts(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    output_path = material_dir / "00-cover-landscape_16_9.jpg"
    request_path = material_dir / "00-cover-landscape_16_9.codex-imagegen.json"
    output_path.write_bytes(b"cover")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(output_path),
                "cover_hard_contract": {
                    "compare_subject_pair_required": True,
                    "full_bitmap_cover_required": True,
                    "brand_model_title_required": True,
                    "config_subtitle_required": True,
                    "required_title_lines": {
                        "brand": "MAXACE",
                        "top": "MAXACE",
                        "main": "美杜莎4",
                        "sub": "顶配vs次顶配",
                        "bottom": "顶配vs次顶配",
                        "hook": "双版本开箱",
                    },
                },
                "cover_director_policy": {
                    "typography_owner": "codex_full_cover",
                },
                "compare_subject_contract_passed": False,
                "compare_subject_contract_reason": "old failure",
                "compare_subject_contract_checked_at": "2026-06-02T00:00:00",
                "compare_subject_contract_check_unavailable": True,
                "bitmap_title_contract_passed": False,
                "bitmap_title_contract_reason": "old failure",
                "bitmap_title_contract_verified_at": "2026-06-02T00:00:00",
                "bitmap_title_contract_check_unavailable": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generation = {
        "image_generation": {
            "request_path": str(request_path),
            "output_path": str(output_path),
            "status": "completed",
            "backend": "codex_builtin",
        }
    }

    async def fake_ensure(**kwargs):
        ic._mark_cover_compare_subject_contract_verified(
            kwargs["request_path"],
            verification={"compare_subject_contract_passed": True, "reason": "ok"},
        )
        ic._mark_cover_bitmap_title_contract_verified(
            kwargs["request_path"],
            title_lines=kwargs["title_lines"],
            verification={
                "bitmap_title_contract_passed": True,
                "main_title_matches": True,
                "subtitle_matches": True,
                "style_consistent": True,
                "detected_main_title": "美杜莎4",
                "detected_subtitle": "顶配vs次顶配",
                "reason": "ok",
            },
        )
        return json.loads(kwargs["request_path"].read_text(encoding="utf-8"))

    monkeypatch.setattr(ic, "_ensure_generated_cover_title_contract_ready", fake_ensure)

    refreshed = await ic._revalidate_existing_cover_generation_request(
        generation=generation,
        output_path=output_path,
        material_dir=material_dir,
        rules={"label": "16:9 横版母版", "cover_size": (1600, 900), "visual_instruction": ""},
        cover_brief={"cover_title": "MAXACE美杜莎4双版开箱"},
    )

    assert refreshed is not None
    assert refreshed["publish_ready"] is True
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["compare_subject_contract_passed"] is True
    assert "compare_subject_contract_check_unavailable" not in payload
    assert payload["bitmap_title_contract_passed"] is True
    assert "bitmap_title_contract_check_unavailable" not in payload


def test_mark_cover_bitmap_title_contract_verified_finalizes_pending_request_with_existing_output(tmp_path) -> None:
    output_path = tmp_path / "00-cover-landscape_4_3.jpg"
    request_path = tmp_path / "00-cover-landscape_4_3.codex-imagegen.json"
    output_path.write_bytes(b"cover")
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "generated_by_codex_bridge": True,
                "output_path": str(output_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ic._mark_cover_bitmap_title_contract_verified(
        request_path,
        title_lines={"main": "美杜莎4", "bottom": "顶配vs次顶配"},
        verification={
            "bitmap_title_contract_passed": False,
            "main_title_matches": False,
            "subtitle_matches": False,
            "style_consistent": True,
            "detected_main_title": "",
            "detected_subtitle": "",
            "reason": "missing titles",
        },
    )

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["completed_at"]
    assert payload["last_attempted_at"]
    assert payload["result_path"] == str(output_path)
    assert payload["bitmap_title_contract_passed"] is False
    assert payload["bitmap_title_contract_reason"] == "missing titles"


def test_mark_cover_bitmap_title_contract_verified_finalizes_container_runtime_output_on_host(tmp_path, monkeypatch) -> None:
    host_output_root = tmp_path / "runtime"
    host_output_root.mkdir()
    output_path = host_output_root / "demo" / "00-cover-landscape_4_3.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"cover")
    request_path = tmp_path / "00-cover-landscape_4_3.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "generated_by_codex_bridge": True,
                "output_path": "/app/data/demo/00-cover-landscape_4_3.jpg",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    ic._mark_cover_bitmap_title_contract_verified(
        request_path,
        title_lines={"main": "美杜莎4", "bottom": "顶配vs次顶配"},
        verification={
            "bitmap_title_contract_passed": True,
            "main_title_matches": True,
            "subtitle_matches": True,
            "style_consistent": True,
            "detected_main_title": "美杜莎4",
            "detected_subtitle": "顶配vs次顶配",
            "reason": "ok",
        },
    )

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["result_path"] == str(output_path)


def test_mark_cover_bitmap_title_contract_verified_does_not_finalize_untrusted_codex_output(tmp_path) -> None:
    output_path = tmp_path / "00-cover-landscape_16_9.jpg"
    request_path = tmp_path / "00-cover-landscape_16_9.codex-imagegen.json"
    output_path.write_bytes(b"fallback")
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "backend": "codex_builtin",
                "output_path": str(output_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ic._mark_cover_bitmap_title_contract_verified(
        request_path,
        title_lines={"main": "美杜莎4", "bottom": "顶配vs次顶配"},
        verification={
            "bitmap_title_contract_passed": False,
            "main_title_matches": False,
            "subtitle_matches": False,
            "style_consistent": False,
            "detected_main_title": "",
            "detected_subtitle": "",
            "reason": "untrusted output",
        },
    )

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pending_codex_imagegen"
    assert "completed_at" not in payload
    assert payload["bitmap_title_contract_reason"] == "untrusted output"


@pytest.mark.asyncio
async def test_drain_pending_cover_group_requests_retries_only_pending_requests(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    pending_output = material_dir / "00-cover-portrait_3_4.jpg"
    pending_request = material_dir / "00-cover-portrait_3_4.codex-imagegen.json"
    completed_output = material_dir / "00-cover-landscape_16_9.jpg"
    completed_request = material_dir / "00-cover-landscape_16_9.codex-imagegen.json"
    pending_output.write_bytes(b"pending")
    completed_output.write_bytes(b"completed")
    pending_request.write_text(
        json.dumps({"status": "pending_codex_imagegen", "output_path": str(pending_output)}, ensure_ascii=False),
        encoding="utf-8",
    )
    completed_request.write_text(
        json.dumps({"status": "completed", "output_path": str(completed_output)}, ensure_ascii=False),
        encoding="utf-8",
    )
    cache = {
        "portrait_3_4": {
            "image_generation": {"request_path": str(pending_request), "output_path": str(pending_output)},
            "cover_group": {"cover_path": str(pending_output)},
        },
        "landscape_16_9": {
            "image_generation": {"request_path": str(completed_request), "output_path": str(completed_output)},
            "cover_group": {"cover_path": str(completed_output)},
        },
    }
    calls: list[tuple[Path, Path]] = []

    async def fake_attempt(*, request_path: Path, output_path: Path, settings):
        calls.append((request_path, output_path))

    monkeypatch.setattr(ic, "_attempt_codex_imagegen_auto_completion", fake_attempt)

    await ic._drain_pending_cover_group_requests(cache=cache, material_dir=material_dir)

    assert calls == [(pending_request, pending_output)]


@pytest.mark.asyncio
async def test_drain_pending_cover_group_requests_records_bridge_error(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    pending_output = material_dir / "00-cover-portrait_9_16.jpg"
    pending_request = material_dir / "00-cover-portrait_9_16.codex-imagegen.json"
    pending_output.write_bytes(b"pending")
    pending_request.write_text(
        json.dumps({"status": "pending_codex_imagegen", "output_path": str(pending_output)}, ensure_ascii=False),
        encoding="utf-8",
    )
    cache = {
        "portrait_9_16": {
            "image_generation": {"request_path": str(pending_request), "output_path": str(pending_output)},
            "cover_group": {"cover_path": str(pending_output)},
        },
    }

    async def fake_attempt(*, request_path: Path, output_path: Path, settings):
        raise RuntimeError("bridge timeout")

    monkeypatch.setattr(ic, "_attempt_codex_imagegen_auto_completion", fake_attempt)

    await ic._drain_pending_cover_group_requests(cache=cache, material_dir=material_dir)

    payload = json.loads(pending_request.read_text(encoding="utf-8"))
    assert "bridge timeout" in payload["auto_completion_error"]
    assert payload["last_attempted_at"]


def test_restore_standard_cover_matrix_group_cache_from_disk_rehydrates_requests(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-portrait_3_4.jpg"
    group_output.write_bytes(b"cover")
    request_path = material_dir / "00-cover-portrait_3_4.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(group_output),
                "codex_runner": {"model": "gpt-5.4-mini"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cache = ic._restore_standard_cover_matrix_group_cache_from_disk(material_dir=material_dir)

    restored = cache["portrait_3_4"]
    assert restored["cover_group"]["cover_path"] == str(group_output)
    assert restored["image_generation"]["request_path"] == str(request_path)
    assert restored["image_generation"]["status"] == "completed"


def test_serialize_cover_matrix_includes_generation_timing_from_request(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    output_path = material_dir / "00-cover-landscape_16_9.jpg"
    request_path = material_dir / "00-cover-landscape_16_9.codex-imagegen.json"
    output_path.write_bytes(b"cover")
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "created_at": "2026-06-02T22:27:06.186131+08:00",
                "completed_at": "2026-06-02T22:28:34.852471+08:00",
                "result_path": "C:/tmp/generated.png",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache = {
        "landscape_16_9": {
            "publish_ready": True,
            "blocking_reasons": [],
            "image_generation": {
                "request_path": str(request_path),
                "output_path": str(output_path),
            },
            "cover_group": {
                "key": "landscape_16_9",
                "label": "16:9 横版母版",
                "cover_path": str(output_path),
                "members": ["bilibili"],
            },
        }
    }

    matrix = ic._serialize_cover_matrix(cache)

    timing = matrix["landscape_16_9"]["generation_timing"]
    assert timing["status"] == "completed"
    assert timing["duration_sec"] == 88.67
    assert timing["result_path"] == "C:/tmp/generated.png"


def test_serialize_cover_matrix_normalizes_naive_request_timestamps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request_path = tmp_path / "cover.codex-imagegen.json"
    output_path = tmp_path / "cover.jpg"
    output_path.write_bytes(b"cover")
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_codex_imagegen",
                "created_at": "2026-06-05T15:41:46.500000",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache = {
        "landscape_16_9": {
            "publish_ready": False,
            "blocking_reasons": [],
            "image_generation": {
                "request_path": str(request_path),
                "output_path": str(output_path),
            },
            "cover_group": {
                "key": "landscape_16_9",
                "label": "16:9 横版母版",
                "cover_path": str(output_path),
                "members": ["bilibili"],
            },
        }
    }
    monkeypatch.setattr(
        ic,
        "datetime",
        SimpleNamespace(
            now=lambda tz=None: datetime(2026, 6, 5, 16, 0, 0, tzinfo=timezone.utc),
            fromisoformat=datetime.fromisoformat,
        ),
    )

    matrix = ic._serialize_cover_matrix(cache)

    timing = matrix["landscape_16_9"]["generation_timing"]
    assert timing["status"] == "pending_codex_imagegen"
    assert timing["created_at"] == "2026-06-05T15:41:46.500000"
    assert timing["duration_sec"] is None
    assert timing["elapsed_sec"] == 1093.5


def test_collect_reusable_platform_materials_ignores_cover_blockers() -> None:
    payload = {
        "platforms": [
            {
                "key": "douyin",
                "label": "抖音",
                "has_title": True,
                "body_label": "描述",
                "tag_label": "标签",
                "titles": ["MAXACE美杜莎4到货了", "顶配次顶配怎么选", "差别都在细节"],
                "primary_title": "MAXACE美杜莎4到货了",
                "title_copy_all": "1. MAXACE美杜莎4到货了",
                "body": "MAXACE美杜莎4到货了，上手看顶配和次顶配的差别。",
                "tags": ["MAXACE", "美杜莎4"],
                "tags_copy": "#MAXACE #美杜莎4",
                "full_copy": "MAXACE美杜莎4到货了\n\nMAXACE美杜莎4到货了，上手看顶配和次顶配的差别。\n\n#MAXACE #美杜莎4",
                "publish_ready": False,
                "blocking_reasons": ["封面图像生成未完成"],
            }
        ]
    }

    reusable = ic._collect_reusable_platform_materials(payload, platform_keys=["douyin"])

    assert list(reusable.keys()) == ["douyin"]
    assert reusable["douyin"]["blocking_reasons"] == ["封面图像生成未完成"]
    assert reusable["douyin"]["body"] == "MAXACE美杜莎4到货了，上手看顶配和次顶配的差别。"


def test_finalize_cover_request_generation_status_recovers_pending_request_after_overlay(tmp_path) -> None:
    output_path = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"
    output_path.write_bytes(b"cover")
    payload = {
        "status": "pending_codex_imagegen",
        "backend": "codex_builtin",
        "output_path": str(output_path),
        "post_title_overlay_applied": True,
    }

    ic._finalize_cover_request_generation_status(request_path=request_path, payload=payload)

    assert payload["status"] == "completed"
    assert payload["result_path"] == str(output_path)
    assert payload["completed_at"]


@pytest.mark.asyncio
async def test_generate_intelligent_copy_ignores_stale_existing_result_when_sources_changed(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "maxace蜂巢3"
    source_dir.mkdir()
    video_path = source_dir / "maxace蜂巢3.mp4"
    subtitle_path = source_dir / "maxace蜂巢3.srt"
    video_path.write_bytes(b"video-v2")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n这期看看蜂巢3的细节\n", encoding="utf-8")

    material_dir = source_dir / "smart-copy"
    material_dir.mkdir()
    result_path = material_dir / "smart-copy.json"
    result_path.write_text(
        json.dumps(
            {
                "source_signature": {
                    "video": {"path": str(video_path), "exists": True, "size": 1, "mtime_ns": 1},
                    "subtitle": {"path": str(subtitle_path), "exists": True, "size": 1, "mtime_ns": 1},
                },
                "platforms": [
                    {
                        "key": "douyin",
                        "label": "抖音",
                        "has_title": True,
                        "body_label": "描述",
                        "tag_label": "标签",
                        "titles": ["旧测试残留标题：顶配次顶配怎么选"],
                        "primary_title": "旧测试残留标题：顶配次顶配怎么选",
                        "title_copy_all": "旧测试残留标题：顶配次顶配怎么选",
                        "body": "旧测试残留正文。",
                        "tags": ["旧标签"],
                        "tags_copy": "#旧标签",
                        "full_copy": "旧测试残留正文。\n\n#旧标签",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "这期看看蜂巢3的细节"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_brand": "maxace", "subject_model": "蜂巢3", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(
        ic,
        "save_platform_packaging_markdown",
        lambda *_args, **_kwargs: None,
    )

    async def fake_generate_platform_packaging(**_kwargs):
        return {
            "highlights": {"product": "maxace蜂巢3"},
            "platforms": {
                "douyin": {
                    "titles": ["maxace蜂巢3开箱先看细节"],
                    "description": "这期围绕maxace蜂巢3展开，重点看细节展示和上手体验。",
                    "tags": ["maxace", "蜂巢3"],
                }
            },
        }

    async def fake_build_cover_brief(**_kwargs):
        return {
            "cover_title": "maxace蜂巢3",
            "video_type": "开箱体验",
            "product_identity": "maxace蜂巢3",
            "selling_angle": "先看细节",
            "visual_brief": "主体真实，标题居中。",
        }

    async def fake_prepare_cover_source(**_kwargs):
        return None

    async def fake_render_cover_group(**_kwargs):
        output_path = Path(_kwargs["output_path"])
        output_path.write_bytes(b"cover")
        return {"publish_ready": True, "blocking_reasons": []}

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_build_intelligent_cover_brief", fake_build_cover_brief)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)

    result = await ic.generate_intelligent_copy(str(source_dir), platforms=["douyin"])

    assert result["platforms"][0]["primary_title"] == "maxace蜂巢3开箱先看细节"
    assert result["platforms"][0]["body"] == "这期围绕maxace蜂巢3展开，重点看细节展示和上手体验。"
    assert "旧测试残留" not in result["platforms"][0]["primary_title"]
    assert any("已忽略与当前视频/字幕不匹配的旧 smart-copy 结果" in warning for warning in result["warnings"])


def test_material_self_heal_fills_safe_publication_metadata() -> None:
    packaging = {
        "platforms": {
            "bilibili": {
                "collection_name": "EDC装备评测合集",
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T19:30",
            }
        }
    }
    material = {
        "key": "bilibili",
        "label": "B站",
        "has_title": True,
        "titles": ["MAXACE美杜莎4到货了"],
        "primary_title": "MAXACE美杜莎4到货了",
        "body": "MAXACE美杜莎4到货了，上手先看细节。",
        "tags": ["MAXACE", "美杜莎4"],
        "full_copy": "MAXACE美杜莎4到货了\n\nMAXACE美杜莎4到货了，上手先看细节。",
        "cover_path": "D:/material/smart-copy/01-bilibili-cover.jpg",
        "copy_material": {},
        "blocking_reasons": [],
    }

    validation = ic._run_material_self_healing(
        packaging=packaging,
        platform_materials=[material],
    )

    assert validation["status"] == "passed"
    assert material["declaration"] == "内容无需标注"
    assert material["collection_name"] == "EDC装备评测合集"
    assert material["collection"]["name"] == "EDC装备评测合集"
    assert material["visibility_or_publish_mode"] == "scheduled"
    assert material["scheduled_publish_at"] == "2026-06-01T19:30"
    assert material["copy_material"]["primary_title"] == "MAXACE美杜莎4到货了"


def test_material_self_heal_keeps_publish_ready_blocked_when_only_preflight_is_blocked() -> None:
    packaging = {
        "platforms": {
            "xiaohongshu": {
                "live_publish_preflight": {
                    "status": "blocked",
                    "missing_required_surfaces": ["schedule"],
                }
            }
        }
    }
    material = {
        "key": "xiaohongshu",
        "label": "小红书",
        "has_title": True,
        "titles": ["新到的美杜莎4"],
        "primary_title": "新到的美杜莎4",
        "body": "两款配置一起到手，先看差别。",
        "tags": ["MAXACE", "美杜莎4"],
        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。",
        "cover_path": "D:/material/smart-copy/01-xiaohongshu-cover.jpg",
        "live_publish_preflight": {
            "status": "blocked",
            "missing_required_surfaces": ["schedule"],
        },
        "copy_material": {},
        "blocking_reasons": [],
    }

    validation = ic._run_material_self_healing(
        packaging=packaging,
        platform_materials=[material],
    )

    assert validation["status"] == "failed"
    assert material["publish_ready"] is False


@pytest.mark.asyncio
async def test_generate_platform_packaging_assesses_only_requested_platforms(monkeypatch) -> None:
    async def fake_repair(prompt, **kwargs):
        return (
            {
                "highlights": {"product": "MAXACE 美杜莎4"},
                "platforms": {
                    "douyin": {
                        "titles": [
                            "MAXACE美杜莎4到货了",
                            "MAXACE美杜莎4顶配次顶配怎么选",
                            "MAXACE美杜莎4双档开箱对比",
                        ],
                        "description": "MAXACE美杜莎4到货了，上手看细节。",
                        "tags": ["MAXACE", "美杜莎4"],
                    },
                    "x": {
                        "titles": [],
                        "description": "这段正文故意写得很泛。",
                        "tags": ["ignored"],
                    },
                },
            },
            [],
        )

    monkeypatch.setattr(pc, "_generate_platform_packaging_with_repair", fake_repair)
    monkeypatch.setattr(pc, "normalize_platform_packaging", lambda raw, **kwargs: raw)

    result = await pc.generate_platform_packaging(
        source_name="MAXACE 美杜莎4 顶配次顶配开箱.mp4",
        content_profile={"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
        subtitle_items=[{"text_final": "MAXACE 美杜莎4 到货了，上手一起看。"}],
        copy_style="attention_grabbing",
        prompt_brief={"mode": "intelligent_copy"},
        fact_sheet={},
        target_platforms=["douyin"],
    )

    assert list(result["platforms"].keys()) == ["douyin"]


@pytest.mark.asyncio
async def test_generate_intelligent_copy_emits_material_validation_and_contract(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    video_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    subtitle_path = source_dir / "MAXACE 美杜莎4 顶配次顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 美杜莎4 到货了\n", encoding="utf-8")

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(source_dir / "smart-copy"),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(ic, "_load_subtitle_items", lambda _path: [{"text_final": "MAXACE 美杜莎4 到货了"}])
    monkeypatch.setattr(ic, "list_packaging_assets", lambda: {"config": {}})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_copy_fast_profile",
        lambda **_kwargs: {"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀"},
    )
    monkeypatch.setattr(ic, "_build_intelligent_copy_brief", lambda **_kwargs: {"topic_subject": "MAXACE 美杜莎4"})
    monkeypatch.setattr(
        ic,
        "generate_platform_packaging",
        lambda **_kwargs: {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "bilibili": {
                    "titles": ["MAXACE美杜莎4到货了", "MAXACE美杜莎4顶配次顶配怎么选", "MAXACE美杜莎4双档开箱对比"],
                    "description": "MAXACE美杜莎4到货了，上手先看细节。",
                    "tags": ["MAXACE", "美杜莎4"],
                    "collection_name": "EDC装备评测合集",
                    "visibility_or_publish_mode": "scheduled",
                    "scheduled_publish_at": "2026-06-01T19:30",
                }
            },
        },
    )
    monkeypatch.setattr(
        ic,
        "_build_intelligent_cover_brief",
        lambda **_kwargs: {
            "cover_title": "MAXACE美杜莎4到货了",
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        },
    )
    monkeypatch.setattr(ic, "save_platform_packaging_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", lambda **_kwargs: None)
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)

    async def fake_render_cover_group(**_kwargs):
        output_path = Path(_kwargs["output_path"])
        output_path.write_bytes(b"cover")
        return {"publish_ready": True, "blocking_reasons": []}

    monkeypatch.setattr(ic, "_render_or_reuse_platform_cover_group", fake_render_cover_group)

    result = await ic.generate_intelligent_copy(
        str(source_dir),
        platforms=["bilibili"],
        creator_profile_id="profile-1",
        creator_profile_name="FAS",
    )

    assert result["material_validation"]["status"] == "passed"
    assert result["material_contract"]["one_click_publish_ready"] is True
    assert result["creator_profile_id"] == "profile-1"
    assert result["creator_profile_name"] == "FAS"
    assert result["publication_context"]["creator_profile_id"] == "profile-1"
    bilibili = result["platforms"][0]
    assert bilibili["declaration"] == "内容无需标注"
    assert bilibili["collection_name"] == "EDC装备评测合集"


@pytest.mark.asyncio
async def test_resolve_packaging_and_cover_context_starts_cover_source_before_packaging_returns(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    material_dir = tmp_path / "smart-copy"
    video_path.write_bytes(b"video")
    material_dir.mkdir()
    cover_started = asyncio.Event()

    async def fake_generate_platform_packaging(**_kwargs):
        await asyncio.wait_for(cover_started.wait(), timeout=0.2)
        return {
            "highlights": {"product": "MAXACE 美杜莎4"},
            "platforms": {
                "douyin": {
                    "titles": ["MAXACE美杜莎4顶配次顶配怎么选", "MAXACE美杜莎4双版本开箱"],
                    "description": "MAXACE美杜莎4到货了。",
                    "tags": ["MAXACE", "美杜莎4"],
                }
            },
        }

    async def fake_prepare_cover_source(**_kwargs):
        cover_started.set()
        return None

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_load_cover_source_manifest", lambda _path: {})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_cover_brief",
        lambda **_kwargs: {
            "cover_title": "MAXACE美杜莎4",
            "video_type": "开箱对比",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配",
            "visual_brief": "主体完整",
        },
    )

    context = await ic._resolve_packaging_and_cover_context(
        video_path=video_path,
        material_dir=material_dir,
        subtitle_items=[{"text_final": "MAXACE 美杜莎4 到货了"}],
        content_profile={"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC折刀", "video_theme": "开箱对比"},
        copy_brief={
            "topic_subject": "MAXACE 美杜莎4",
            "intent": "开箱对比",
            "focus_points": ["顶配", "次顶配"],
            "question": "怎么选",
        },
        existing_packaging={},
        selected_platform_keys=["douyin"],
        platforms_requiring_regeneration=["douyin"],
        resolved_copy_style="attention_grabbing",
        existing_result=None,
        existing_cover_path=None,
    )

    assert cover_started.is_set()
    assert context["packaging"]["platforms"]["douyin"]["titles"]


@pytest.mark.asyncio
async def test_resolve_packaging_and_cover_context_falls_back_to_local_packaging_on_timeout(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱.mp4"
    material_dir = tmp_path / "smart-copy"
    video_path.write_bytes(b"video")
    material_dir.mkdir()

    async def fake_generate_platform_packaging(**_kwargs):
        raise asyncio.TimeoutError()

    async def fake_prepare_cover_source(**_kwargs):
        return None

    monkeypatch.setattr(ic, "generate_platform_packaging", fake_generate_platform_packaging)
    monkeypatch.setattr(ic, "_prepare_intelligent_copy_cover_source", fake_prepare_cover_source)
    monkeypatch.setattr(ic, "_load_cover_source_manifest", lambda _path: {})
    monkeypatch.setattr(
        ic,
        "_build_intelligent_cover_brief",
        lambda **_kwargs: {
            "cover_title": "MAXACE美杜莎4",
            "video_type": "开箱对比",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配",
            "visual_brief": "主体完整",
        },
    )

    context = await ic._resolve_packaging_and_cover_context(
        video_path=video_path,
        material_dir=material_dir,
        subtitle_items=[{"text_final": "MAXACE 美杜莎4 到货了"}],
        content_profile={"subject_model": "MAXACE 美杜莎4", "subject_type": "EDC跳刀", "video_theme": "开箱对比"},
        copy_brief={
            "topic_subject": "MAXACE 美杜莎4",
            "intent": "开箱对比",
            "focus_points": ["顶配", "次顶配"],
            "question": "怎么选",
        },
        existing_packaging={},
        selected_platform_keys=["douyin"],
        platforms_requiring_regeneration=["douyin"],
        resolved_copy_style="attention_grabbing",
        existing_result=None,
        existing_cover_path=None,
    )

    assert context["packaging"]["platforms"]["douyin"]["titles"]
    assert "MAXACE 美杜莎4" in context["packaging"]["highlights"]["product"]


def test_upgrade_existing_intelligent_copy_result_restores_group_cover_and_contract(tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    group_cover_34 = material_dir / "00-cover-portrait_3_4.jpg"
    group_cover_916 = material_dir / "00-cover-portrait_9_16.jpg"
    group_cover_34.write_bytes(b"cover-34")
    group_cover_916.write_bytes(b"cover-916")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "话题",
                        "constraints": {"title_limit": 20, "body_limit": 1000, "tag_limit": 8, "tag_style": "hashtags_space"},
                        "titles": ["新到的美杜莎4"],
                        "primary_title": "新到的美杜莎4",
                        "title_copy_all": "1. 新到的美杜莎4",
                        "body": "两款配置一起到手，先看差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。\n\n#MAXACE #美杜莎4",
                        "cover_path": None,
                        "cover_generation": {
                            "publish_ready": False,
                            "blocking_reasons": ["封面图像生成未完成"],
                            "cover_group": {"cover_path": str(group_cover_34)},
                        },
                        "publish_ready": False,
                        "blocking_reasons": ["封面图像生成未完成"],
                    },
                    {
                        "key": "douyin",
                        "label": "抖音",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "简介",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 55, "body_limit": 300, "tag_limit": 5, "tag_style": "hashtags_space"},
                        "titles": ["美杜莎4双版开箱对比"],
                        "primary_title": "美杜莎4双版开箱对比",
                        "title_copy_all": "1. 美杜莎4双版开箱对比",
                        "body": "顶配次顶配一起上手，差别很直观。",
                        "tags": ["MAXACE", "美杜莎4", "开箱对比"],
                        "tags_copy": "#MAXACE #美杜莎4 #开箱对比",
                        "full_copy": "美杜莎4双版开箱对比\n\n顶配次顶配一起上手，差别很直观。\n\n#MAXACE #美杜莎4 #开箱对比",
                        "cover_path": None,
                        "cover_generation": {
                            "publish_ready": False,
                            "blocking_reasons": ["封面图像生成未完成"],
                            "cover_group": {"cover_path": str(group_cover_916)},
                        },
                        "publish_ready": False,
                        "blocking_reasons": ["封面图像生成未完成"],
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["xiaohongshu", "douyin"],
        platform_options={
            "xiaohongshu": {
                "scheduled_publish_at": "2026-06-01T21:00",
                "visibility_or_publish_mode": "scheduled",
                "collection_name": "EDC潮玩桌搭",
                "platform_specific_overrides": {
                    "selected_declarations": ["原创声明"],
                    "selected_group_chat": "F.A.S EDC畅聊群",
                },
            },
            "douyin": {
                "scheduled_publish_at": "2026-06-01T20:30",
                "visibility_or_publish_mode": "scheduled",
                "platform_specific_overrides": {
                    "collection_management": {"status": "needs_create", "target_collection_name": "EDC潮玩桌搭"},
                },
            },
        },
    )

    assert result["material_validation"]["status"] == "passed"
    assert result["material_contract"]["one_click_publish_ready"] is True
    assert result["material_contract"]["platforms"]["xiaohongshu"]["cover_ready"] is True
    assert result["material_contract"]["platforms"]["douyin"]["cover_ready"] is True
    assert (material_dir / "01-xiaohongshu-cover.jpg").exists()
    assert (material_dir / "02-douyin-cover.jpg").exists()
    assert (material_dir / "platform-packaging.json").exists()

    payload = json.loads(smart_copy_path.read_text(encoding="utf-8"))
    assert payload["platforms"][0]["cover_path"].endswith("01-xiaohongshu-cover.jpg")
    assert payload["platforms"][1]["cover_path"].endswith("02-douyin-cover.jpg")
    assert payload["platforms"][0]["declaration"] == "原创声明"
    assert payload["platforms"][0]["collection_name"] == "EDC潮玩桌搭"
    assert payload["platforms"][1]["visibility_or_publish_mode"] == "scheduled"


def test_upgrade_existing_intelligent_copy_result_reannotates_persisted_single_subject_cover_brief(tmp_path) -> None:
    source_dir = tmp_path / "maxace蜂巢3顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "creator_profile_name": "FAS",
                "content_profile_summary": {
                    "subject_brand": "maxace",
                    "subject_model": "蜂巢3顶配",
                    "subject_type": "EDC折刀",
                    "summary": "这期围绕EDC折刀展开，重点看开箱过程、细节展示和上手体验。",
                },
                "cover_brief": {
                    "cover_title": "maxace蜂巢3顶配开箱",
                    "product_identity": "maxace蜂巢3顶配EDC折刀",
                    "selling_angle": "细节做工与上手质感",
                    "visual_brief": "主体真实，突出做工细节。",
                    "video_type": "开箱",
                    "style_key": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
                    "strategy_axes": {
                        "content_scheme": {"key": "unboxing_single_subject_v1"},
                        "subject_fidelity_scheme": {"key": "generic_subject_fidelity_v1"},
                    },
                },
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "简介",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "hashtags_space"},
                        "titles": ["maxace蜂巢3顶配开箱"],
                        "primary_title": "maxace蜂巢3顶配开箱",
                        "title_copy_all": "1. maxace蜂巢3顶配开箱",
                        "body": "这期主要看细节做工和上手质感。",
                        "tags": ["maxace", "蜂巢3顶配"],
                        "tags_copy": "#maxace #蜂巢3顶配",
                        "full_copy": "maxace蜂巢3顶配开箱\n\n这期主要看细节做工和上手质感。\n\n#maxace #蜂巢3顶配",
                        "cover_path": None,
                        "publish_ready": False,
                        "blocking_reasons": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ic.upgrade_existing_intelligent_copy_result(str(source_dir), platforms=["bilibili"])

    assert result["cover_brief"]["strategy_axes"]["content_scheme"]["key"] == "unboxing_single_subject_v1"
    assert result["cover_brief"]["strategy_axes"]["subject_fidelity_scheme"]["key"] == "generic_subject_fidelity_v1"


def test_upgrade_existing_intelligent_copy_result_blocks_persisted_fallback_contracts(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "maxace蜂巢3顶配开箱"
    source_dir.mkdir(parents=True)
    video_path = source_dir / "maxace蜂巢3顶配开箱.mp4"
    subtitle_path = source_dir / "maxace蜂巢3顶配开箱.srt"
    video_path.write_bytes(b"video")
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nMAXACE 蜂巢3 顶配到货了\n", encoding="utf-8")
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    smart_copy_path = ic.smart_copy_material_json_path(material_dir)
    smart_copy_path.parent.mkdir(parents=True, exist_ok=True)
    original_payload = {
        "folder_path": str(source_dir),
        "material_dir": str(material_dir),
        "markdown_path": str(ic.smart_copy_platform_packaging_markdown_path(material_dir)),
        "json_path": str(smart_copy_path),
        "copy_style": "attention_grabbing",
        "content_profile_summary": {
            "subject_brand": "MAXACE",
            "subject_model": "蜂巢3顶配",
            "subject_type": "EDC折刀",
        },
        "cover_brief": {
            "cover_title": "maxace蜂巢3顶配开箱",
            "product_identity": "maxace蜂巢3顶配EDC折刀",
            "selling_angle": "细节做工与上手质感",
            "visual_brief": "主体真实，突出做工细节。",
            "video_type": "开箱",
            "strategy_source": "fallback",
        },
        "platforms": [
            {
                "key": "bilibili",
                "label": "B站",
                "has_title": True,
                "title_label": "标题",
                "body_label": "简介",
                "tag_label": "标签",
                "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "hashtags_space"},
                "titles": ["maxace蜂巢3顶配开箱"],
                "primary_title": "maxace蜂巢3顶配开箱",
                "title_copy_all": "1. maxace蜂巢3顶配开箱",
                "body": "这期主要看细节做工和上手质感。",
                "tags": ["maxace", "蜂巢3顶配"],
                "tags_copy": "#maxace #蜂巢3顶配",
                "full_copy": "maxace蜂巢3顶配开箱\n\n这期主要看细节做工和上手质感。\n\n#maxace #蜂巢3顶配",
                "cover_path": None,
                "publish_ready": False,
                "blocking_reasons": [],
            }
        ],
    }
    smart_copy_path.write_text(
        json.dumps(original_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    platform_packaging_path = ic.smart_copy_platform_packaging_json_path(material_dir)
    platform_packaging_path.parent.mkdir(parents=True, exist_ok=True)
    platform_packaging_path.write_text(
        json.dumps(
            {
                "highlights": {"product": "MAXACE 蜂巢3顶配"},
                "generation_repair_trace": [{"status": "deterministic_fallback", "reason": "llm timeout"}],
                "platforms": {"bilibili": {}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "inspect_intelligent_copy_folder",
        lambda _folder: {
            "folder_path": str(source_dir),
            "material_dir": str(material_dir),
            "video_file": str(video_path),
            "subtitle_file": str(subtitle_path),
            "cover_file": None,
            "extra_video_files": [],
            "extra_subtitle_files": [],
            "extra_cover_files": [],
            "warnings": [],
        },
    )

    result = ic.upgrade_existing_intelligent_copy_result(str(source_dir), platforms=["bilibili"])

    assert result["status"] == "blocked"
    assert result["publish_ready"] is False
    assert result["platforms"] == []
    assert "platform_packaging_deterministic_fallback" in result["blocking_reasons"]
    assert "intelligent_copy_cover_brief_fallback" in result["blocking_reasons"]
    assert json.loads(smart_copy_path.read_text(encoding="utf-8")) == original_payload
    assert json.loads(platform_packaging_path.read_text(encoding="utf-8"))["generation_repair_trace"][0]["status"] == "deterministic_fallback"


def test_resolve_cover_canvas_fit_mode_prefers_blur_fill_for_large_ratio_mismatch(tmp_path) -> None:
    source = tmp_path / "landscape.jpg"
    Image.new("RGB", (1600, 900), (24, 48, 72)).save(source)

    assert ic._resolve_cover_canvas_fit_mode(
        source_path=source,
        width=1080,
        height=1920,
    ) == "blur_fill"


def test_render_or_reuse_existing_cover_group_uses_cover_fit_for_portrait_matrix(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    output_path = material_dir / "02-douyin-cover.jpg"
    existing_cover = material_dir / "source.jpg"
    Image.new("RGB", (1600, 900), (24, 48, 72)).save(existing_cover)

    seen: list[str] = []

    def fake_fit_image_to_canvas(**kwargs):
        seen.append(kwargs["fit_mode"])
        Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1440), (24, 48, 72)).save(kwargs["output_path"])

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)

    result = ic._render_or_reuse_existing_cover_group(
        cache={},
        material_dir=material_dir,
        output_path=output_path,
        existing_cover_path=existing_cover,
        platform_key="douyin",
        platform_rules={"cover_size": (1080, 1440), "label": "抖音"},
        cover_group={
            "key": "portrait_3_4",
            "label": "3:4 竖版",
            "cover_size": (1080, 1440),
            "representative_platform": "douyin",
            "members": ["douyin"],
        },
    )

    assert "cover" in seen
    assert result["publish_ready"] is True
    assert output_path.exists()


@pytest.mark.asyncio
async def test_render_or_reuse_platform_cover_group_passes_matrix_visual_instruction(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    output_path = material_dir / "03-douyin-cover.jpg"
    source_image = material_dir / "source.jpg"
    source_image.write_bytes(b"source")
    cache: dict[str, dict[str, object]] = {}
    captured_rules: dict[str, object] = {}

    async def fake_render_platform_cover(**kwargs):
        captured_rules.update(dict(kwargs["rules"]))
        Path(kwargs["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["output_path"]).write_bytes(b"group-cover")
        return {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(kwargs["output_path"]),
        }

    monkeypatch.setattr(ic, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", lambda **kwargs: Path(kwargs["output_path"]).write_bytes(b"cover"))

    cover_group = ic._cover_matrix_group_profile("landscape_4_3")
    platform_rules = dict(ic.PLATFORM_PUBLISH_RULES["douyin"])

    result = await ic._render_or_reuse_platform_cover_group(
        cache=cache,
        material_dir=material_dir,
        output_path=output_path,
        video_path=tmp_path / "video.mp4",
        source_image_path=source_image,
        existing_cover_path=None,
        title="MAXACE 美杜莎4 顶配vs次顶配",
        platform_key="douyin",
        platform_rules=platform_rules,
        cover_group=cover_group,
        cover_brief={"product_identity": "MAXACE 美杜莎4"},
    )

    assert captured_rules["visual_instruction"] == cover_group["visual_instruction"]
    assert output_path.exists()
    assert cache["landscape_4_3"]["cover_group"]["key"] == "landscape_4_3"


def test_material_contract_blocks_one_click_when_live_publish_preflight_is_blocked() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "xiaohongshu",
                "label": "小红书",
                "cover_path": "E:/covers/xhs.jpg",
                "blocking_reasons": [],
                "declaration": "原创声明",
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T20:30",
                "platform_specific_overrides": {
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["schedule"],
                    }
                },
            },
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/dy.jpg",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T20:30",
                "platform_specific_overrides": {"skip_collection_select": True},
            },
        ]
    )

    assert contract["status"] == "failed"
    assert contract["one_click_publish_ready"] is False
    assert contract["platforms"]["xiaohongshu"]["status"] == "failed"
    assert contract["platforms"]["xiaohongshu"]["one_click_publish_ready"] is False
    assert contract["platforms"]["xiaohongshu"]["live_publish_preflight_ready"] is False
    assert "live_publish_preflight" in contract["platforms"]["xiaohongshu"]["missing_fields"]
    assert any("schedule" in reason for reason in contract["blocking_reasons"])
    assert contract["platforms"]["douyin"]["status"] == "passed"
    assert contract["platforms"]["douyin"]["one_click_publish_ready"] is True


def test_material_generation_contract_ignores_publish_gate_only_cover_blockers() -> None:
    material = {
        "key": "bilibili",
        "label": "B站",
        "has_title": True,
        "titles": ["MAXACE美杜莎4双版本开箱"],
        "primary_title": "MAXACE美杜莎4双版本开箱",
        "body": "正文",
        "tags": ["EDC", "MAXACE"],
        "full_copy": "完整文案",
        "cover_path": r"Z:\demo\00-cover-landscape_16_9.jpg",
        "declaration": "无需添加自主声明",
        "platform_specific_overrides": {"collection_policy": "skip", "skip_collection_select": True},
        "cover_generation": {
            "publish_ready": False,
            "blocking_reasons": [
                "完整封面位图标题校验未完成，不能放行到最终封面",
                "封面主标题未稳定锁定品牌/型号，存在内容签名漂移风险",
            ],
            "image_generation": {
                "backend": "codex_builtin",
                "status": "completed",
                "output_path": r"Z:\demo\00-cover-landscape_16_9.jpg",
            },
        },
        "blocking_reasons": [
            "完整封面位图标题校验未完成，不能放行到最终封面",
            "封面主标题未稳定锁定品牌/型号，存在内容签名漂移风险",
        ],
    }

    generation_contract = ic._build_material_generation_contract([material], requested_platforms=["bilibili"])
    publish_contract = ic._build_material_contract([material], requested_platforms=["bilibili"])

    assert generation_contract["status"] == "passed"
    assert generation_contract["generation_ready"] is True
    assert generation_contract["platforms"]["bilibili"]["generation_ready"] is True
    assert publish_contract["status"] == "failed"
    assert publish_contract["one_click_publish_ready"] is False


def test_material_generation_contract_ignores_missing_collection_policy_when_artifacts_exist() -> None:
    material = {
        "key": "bilibili",
        "label": "B站",
        "has_title": True,
        "titles": ["MAXACE美杜莎4双版本开箱"],
        "primary_title": "MAXACE美杜莎4双版本开箱",
        "body": "正文",
        "tags": ["EDC", "MAXACE"],
        "full_copy": "完整文案",
        "cover_path": r"Z:\demo\00-cover-landscape_16_9.jpg",
    }

    generation_contract = ic._build_material_generation_contract([material], requested_platforms=["bilibili"])
    publish_contract = ic._build_material_contract([material], requested_platforms=["bilibili"])

    assert generation_contract["status"] == "passed"
    assert generation_contract["generation_ready"] is True
    assert generation_contract["platforms"]["bilibili"]["generation_ready"] is True
    assert publish_contract["status"] == "failed"
    assert any("合集决策" in reason for reason in publish_contract["blocking_reasons"])


def test_platform_packaging_export_includes_material_generation_contract() -> None:
    material = {
        "key": "bilibili",
        "label": "B站",
        "has_title": True,
        "titles": ["MAXACE美杜莎4双版本开箱"],
        "primary_title": "MAXACE美杜莎4双版本开箱",
        "body": "正文",
        "tags": ["EDC"],
        "full_copy": "完整文案",
        "cover_path": r"Z:\demo\00-cover-landscape_16_9.jpg",
        "declaration": "无需添加自主声明",
        "platform_specific_overrides": {"collection_policy": "skip", "skip_collection_select": True},
        "blocking_reasons": ["完整封面位图标题校验未完成，不能放行到最终封面"],
        "publish_ready": False,
        "cover_generation": {
            "publish_ready": False,
            "blocking_reasons": ["完整封面位图标题校验未完成，不能放行到最终封面"],
            "image_generation": {"backend": "codex_builtin", "status": "completed"},
        },
    }

    export_payload = ic._build_platform_packaging_export(
        packaging={"platforms": {}, "highlights": {}},
        platform_materials=[material],
        requested_platforms=["bilibili"],
        cover_matrix={},
    )

    assert export_payload["material_generation_status"] == "passed"
    assert export_payload["material_generation_ready"] is True
    assert export_payload["status"] == "passed"
    assert export_payload["material_generation_contract"]["platforms"]["bilibili"]["generation_ready"] is True
    assert export_payload["one_click_publish_ready"] is False
    assert export_payload["platforms"]["bilibili"]["publish_ready"] is False
    assert export_payload["platforms"]["bilibili"]["one_click_publish_ready"] is False


def test_apply_material_contract_export_state_preserves_one_click_ready_during_manual_handoff() -> None:
    payload: dict[str, object] = {}
    contract = {
        "status": "manual_handoff",
        "one_click_publish_ready": True,
        "manual_handoff_platforms": ["wechat-channels"],
        "blocking_reasons": [],
    }

    ic._apply_material_contract_export_state(payload, contract, blocking_reasons=[])

    assert payload["status"] == "manual_handoff"
    assert payload["publish_ready"] is False
    assert payload["one_click_publish_ready"] is True
    assert payload["manual_handoff_ready"] is True
    assert payload["manual_handoff_targets"] == ["wechat-channels"]
    assert payload["blocking_reasons"] == []


def test_apply_material_generation_export_state_prefers_generation_success_over_publish_block() -> None:
    payload: dict[str, object] = {
        "status": "failed",
        "publish_ready": False,
        "one_click_publish_ready": False,
    }

    ic._apply_material_generation_export_state(
        payload,
        {"status": "passed", "generation_ready": True},
        material_contract={"status": "failed", "one_click_publish_ready": False},
    )

    assert payload["status"] == "passed"
    assert payload["material_generation_status"] == "passed"
    assert payload["material_generation_ready"] is True


def test_upgrade_existing_intelligent_copy_result_accepts_explicit_bilibili_platform_options_for_old_materials(
    tmp_path,
) -> None:
    source_dir = tmp_path / "MOT 风灵音叉推牌 锆合金版本"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "01-bilibili-cover.jpg").write_bytes(b"cover")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "csv"},
                        "titles": ["锆合金版风灵音叉推牌来了，质感真不一样"],
                        "primary_title": "锆合金版风灵音叉推牌来了，质感真不一样",
                        "title_copy_all": "1. 锆合金版风灵音叉推牌来了，质感真不一样",
                        "body": "到手最直接的感受就是扎实，锆合金的版本比常规版本沉一些。",
                        "tags": ["MOT风灵", "音叉推牌", "EDC玩具"],
                        "tags_copy": "MOT风灵, 音叉推牌, EDC玩具",
                        "full_copy": "锆合金版风灵音叉推牌来了，质感真不一样\n\n到手最直接的感受就是扎实，锆合金的版本比常规版本沉一些。",
                        "cover_path": str(material_dir / "01-bilibili-cover.jpg"),
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["bilibili"],
        platform_options={
            "bilibili": {
                "scheduled_publish_at": "2026-06-02T19:30",
                "visibility_or_publish_mode": "scheduled",
                "category": "户外潮流",
                "platform_specific_overrides": {
                    "selected_declarations": ["原创"],
                    "collection_management": {
                        "status": "needs_create",
                        "target_collection_name": "EDC潮玩桌搭",
                    },
                },
            }
        },
    )

    assert result["status"] == "passed"
    assert result["publish_ready"] is True
    assert result["material_contract"]["status"] == "passed"
    assert result["material_contract"]["one_click_publish_ready"] is True
    assert result["material_contract"]["platform_scope"]["requested_platforms"] == ["bilibili"]
    assert result["material_contract"]["platforms"]["bilibili"]["publication_metadata_ready"] is True
    assert result["material_contract"]["platforms"]["bilibili"]["collection_policy_ready"] is True

    payload = json.loads(smart_copy_path.read_text(encoding="utf-8"))
    material = payload["platforms"][0]
    assert material["declaration"] == "原创"
    assert material["category"] == "户外潮流"
    assert material["visibility_or_publish_mode"] == "scheduled"
    assert material["scheduled_publish_at"] == "2026-06-02T19:30"
    assert material["platform_specific_overrides"]["collection_management"]["target_collection_name"] == "EDC潮玩桌搭"


def test_material_contract_defaults_to_skip_collection_when_unspecified() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/dy.jpg",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T20:30",
                "platform_specific_overrides": {},
            },
            {
                "key": "toutiao",
                "label": "头条号",
                "cover_path": "E:/covers/toutiao.jpg",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T21:00",
                "platform_specific_overrides": {"skip_collection_select": True},
            },
        ]
    )

    assert contract["platforms"]["douyin"]["collection_policy_ready"] is True
    assert "collection_policy" not in contract["platforms"]["douyin"]["missing_fields"]
    assert contract["platforms"]["toutiao"]["collection_policy_ready"] is True


def test_material_contract_uses_shared_matrix_for_xiaohongshu_cover_and_collection_policy() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "xiaohongshu",
                "label": "小红书",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T21:00",
                "platform_specific_overrides": {},
            },
            {
                "key": "x",
                "label": "X",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-06-01T09:30",
                "platform_specific_overrides": {},
            },
        ]
    )

    assert contract["status"] == "failed"
    xhs = contract["platforms"]["xiaohongshu"]
    assert xhs["cover_ready"] is False
    assert xhs["collection_policy_ready"] is True
    assert "cover_path" in xhs["missing_fields"]
    assert "collection_policy" not in xhs["missing_fields"]
    x_entry = contract["platforms"]["x"]
    assert x_entry["cover_ready"] is True
    assert x_entry["collection_policy_ready"] is True
    assert x_entry["publication_metadata_ready"] is True


def test_derive_safe_platform_specific_overrides_defaults_explicit_collection_skip_for_bilibili() -> None:
    overrides = ic._derive_safe_platform_specific_overrides(
        platform_key="bilibili",
        material={},
        platform_payload={},
    )

    assert overrides["skip_collection_select"] is True
    assert overrides["collection_policy"] == "skip"


def test_apply_creator_publication_policy_to_material_projects_collection_management() -> None:
    material = {
        "key": "bilibili",
        "label": "B站",
        "body": "这期是 FAS 新品开箱，上手看看细节。",
        "tags": ["FAS", "新品开箱"],
    }

    ic._apply_creator_publication_policy_to_material(
        platform_key="bilibili",
        material=material,
        platform_payload={"titles": ["FAS 新品开箱"], "description": "这期是 FAS 新品开箱，上手看看细节。"},
        creator_publication_policy={
            "version": 1,
            "source": "creator_profile",
            "rules": [
                {
                    "id": "fas-bili-collection",
                    "source": "creator_profile",
                    "type": "preferred_collection",
                    "platforms": ["bilibili"],
                    "preferred_collection_name": "FAS新品",
                }
            ],
        },
        creator_profile_name="FAS",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
    )

    overrides = material["platform_specific_overrides"]
    assert overrides["collection_management"]["status"] == "needs_create"
    assert overrides["collection_management"]["target_collection_name"] == "FAS新品"
    assert "skip_collection_select" not in overrides
    assert material.get("collection_name", "") == ""


def test_refresh_platform_material_cover_generation_status_materializes_group_derivative(tmp_path, monkeypatch) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    group_output = material_dir / "00-cover-landscape_16_9.jpg"
    group_output.write_bytes(b"cover")
    request_path = material_dir / "00-cover-landscape_16_9.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "output_path": str(group_output),
                "result_path": str(group_output),
                "generated_by_codex_bridge": True,
                "completed_at": "2026-06-09T10:00:00+08:00",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    material = {
        "key": "x",
        "label": "X",
        "body": "正文",
        "tags": ["FAS"],
        "platform_specific_overrides": {},
        "cover_generation": {
            "source": "cover_group_reuse",
            "cover_group": {"key": "landscape_16_9", "cover_path": str(group_output)},
            "group_generation": {
                "image_generation": {
                    "status": "completed",
                    "backend": "codex_builtin",
                    "request_path": str(request_path),
                    "output_path": str(group_output),
                },
                "cover_group": {"key": "landscape_16_9", "cover_path": str(group_output)},
                "blocking_reasons": [],
                "publish_ready": True,
            },
        },
    }
    monkeypatch.setattr(
        ic,
        "_fit_image_to_canvas",
        lambda *, source_path, output_path, width, height, fit_mode="contain": output_path.write_bytes(source_path.read_bytes()),
    )
    monkeypatch.setattr(ic, "_write_platform_material_files", lambda **_kwargs: None)

    ic._refresh_platform_material_cover_generation_status(material_dir=material_dir, platform_materials=[material])

    expected_cover = ic.smart_copy_platform_cover_path(material_dir, ic._resolve_platform_material_serial("x"), "x")
    assert material["cover_path"] == str(expected_cover)
    assert expected_cover.exists()
    assert "封面等待 Codex 内置 imagegen 执行完成" not in material.get("blocking_reasons", [])


def test_normalize_existing_platform_material_omits_empty_publication_metadata() -> None:
    rules = dict(ic.PLATFORM_PUBLISH_RULES["x"])
    material = ic._normalize_existing_platform_material(
        {
            "key": "x",
            "label": "X",
            "has_title": False,
            "body": "body",
            "tags": ["MAXACE"],
            "cover_path": "E:/covers/x.jpg",
            "declaration": "",
            "category": "",
            "collection_name": "",
            "visibility_or_publish_mode": "",
            "scheduled_publish_at": "",
        },
        rules=rules,
    )

    for field in ("declaration", "category", "collection_name", "visibility_or_publish_mode", "scheduled_publish_at"):
        assert field not in material

    contract = ic._build_material_contract([material])
    assert contract["platforms"]["x"]["publication_metadata_ready"] is True


def test_packaging_from_existing_intelligent_copy_result_omits_empty_publication_metadata() -> None:
    packaging = ic._packaging_from_existing_intelligent_copy_result(
        {
            "platforms": [
                {
                    "key": "x",
                    "body": "body",
                    "tags": ["MAXACE"],
                    "cover_path": "E:/covers/x.jpg",
                    "declaration": "",
                    "category": "",
                    "collection_name": "",
                    "visibility_or_publish_mode": "",
                    "scheduled_publish_at": "",
                }
            ]
        },
        platform_keys=["x"],
    )

    x_entry = packaging["platforms"]["x"]
    for field in ("declaration", "category", "collection_name", "visibility_or_publish_mode", "scheduled_publish_at"):
        assert field not in x_entry


def test_material_contract_persists_requested_platform_scope() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/douyin.jpg",
                "blocking_reasons": [],
                "declaration": "无需添加自主声明",
                "collection_name": "EDC潮玩桌搭",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "live_publish_preflight": {"status": "ready"},
                "platform_specific_overrides": {"collection_policy": "named"},
            }
        ],
        requested_platforms=["douyin", "xiaohongshu"],
    )

    assert contract["status"] == "failed"
    assert contract["basic_publish_ready"] is False
    assert contract["one_click_publish_ready"] is False
    assert contract["platform_scope"]["requested_platforms"] == ["douyin", "xiaohongshu"]
    assert contract["platform_scope"]["covered_platforms"] == ["douyin"]
    assert contract["platform_scope"]["missing_requested_platforms"] == ["xiaohongshu"]
    assert contract["blocking_reasons"] == [
        "发布范围不匹配：xiaohongshu 不在本期物料生成范围内。当前仅覆盖平台 -> douyin"
    ]


def test_material_contract_normalizes_generate_publish_platform_tuples() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/douyin.jpg",
                "blocking_reasons": [],
                "declaration": "无需添加自主声明",
                "collection_name": "EDC潮玩桌搭",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "live_publish_preflight": {"status": "ready"},
                "platform_specific_overrides": {"collection_policy": "named"},
            }
        ],
        requested_platforms=[
            ("douyin", "抖音", "简介", "标签"),
            ("xiaohongshu", "小红书", "正文", "话题"),
        ],
    )

    assert contract["platform_scope"]["requested_platforms"] == ["douyin", "xiaohongshu"]
    assert contract["platform_scope"]["covered_platforms"] == ["douyin"]
    assert contract["platform_scope"]["missing_requested_platforms"] == ["xiaohongshu"]
    assert contract["status"] == "failed"


def test_upgrade_existing_intelligent_copy_result_fails_closed_when_requested_platform_is_outside_material_scope(
    tmp_path,
) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)

    payload = {
        "platforms": [
            {
                "key": "douyin",
                "label": "抖音",
                "titles": ["抖音标题"],
                "primary_title": "抖音标题",
                "body": "抖音正文",
                "tags": ["EDC"],
                "full_copy": "抖音标题\n\n抖音正文\n\n#EDC",
                "cover_path": "E:/covers/douyin.jpg",
                "blocking_reasons": [],
                "declaration": "无需添加自主声明",
                "collection_name": "EDC潮玩桌搭",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "live_publish_preflight": {"status": "ready"},
                "platform_specific_overrides": {"collection_policy": "named"},
            }
        ],
        "material_contract": {
            "status": "passed",
            "one_click_publish_ready": True,
            "platform_scope": {
                "requested_platforms": ["douyin"],
                "covered_platforms": ["douyin"],
                "missing_requested_platforms": [],
            },
            "platforms": {
                "douyin": {
                    "status": "passed",
                    "one_click_publish_ready": True,
                    "missing_fields": [],
                    "blocking_reasons": [],
                }
            },
        },
    }
    (material_dir / "smart-copy.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "platform_scope": {
                    "requested_platforms": ["douyin"],
                    "covered_platforms": ["douyin"],
                    "missing_requested_platforms": [],
                },
                "platforms": {
                    "douyin": {
                        "titles": ["抖音标题"],
                        "description": "抖音正文",
                        "cover_path": "E:/covers/douyin.jpg",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    upgraded = ic.upgrade_existing_intelligent_copy_result(str(source_dir), platforms=["bilibili"])

    assert upgraded["status"] == "failed"
    assert upgraded["publish_ready"] is False
    assert upgraded["material_contract"]["status"] == "failed"
    assert upgraded["material_contract"]["one_click_publish_ready"] is False
    assert upgraded["material_contract"]["platform_scope"]["requested_platforms"] == ["bilibili"]
    assert upgraded["material_contract"]["platform_scope"]["covered_platforms"] == []
    assert upgraded["material_contract"]["platform_scope"]["missing_requested_platforms"] == ["bilibili"]
    assert upgraded["blocking_reasons"] == [
        "发布范围不匹配：bilibili 不在本期物料生成范围内。当前仅覆盖平台 -> 无"
    ]
    assert upgraded["material_validation"]["status"] == "failed"
    assert upgraded["material_validation"]["final_contract"]["status"] == "failed"
    assert upgraded["material_validation"]["final_contract"]["one_click_publish_ready"] is False
    assert upgraded["material_validation"]["final_contract"]["platform_scope"]["requested_platforms"] == ["bilibili"]
    assert upgraded["material_validation"]["final_contract"]["platform_scope"]["missing_requested_platforms"] == ["bilibili"]
    assert upgraded["material_validation"]["final_contract"]["blocking_reasons"] == [
        "发布范围不匹配：bilibili 不在本期物料生成范围内。当前仅覆盖平台 -> 无"
    ]


def test_material_contract_excludes_manual_handoff_platforms_from_one_click_failure() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/douyin.jpg",
                "blocking_reasons": [],
                "declaration": "无需添加自主声明",
                "collection_name": "EDC潮玩桌搭",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "live_publish_preflight": {"status": "ready"},
                "platform_specific_overrides": {"collection_policy": "named"},
            },
            {
                "key": "wechat-channels",
                "label": "视频号",
                "blocking_reasons": [],
                "cover_path": "",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "platform_specific_overrides": {},
            },
        ],
        requested_platforms=["douyin", "wechat-channels"],
    )

    assert contract["status"] == "manual_handoff"
    assert contract["one_click_publish_ready"] is True
    assert contract["platforms"]["douyin"]["one_click_publish_ready"] is True
    assert contract["platforms"]["wechat-channels"]["manual_handoff_only"] is True
    assert contract["manual_handoff_platforms"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert all("视频号" not in reason for reason in contract["blocking_reasons"])


def test_material_self_healing_preserves_manual_handoff_status(monkeypatch) -> None:
    monkeypatch.setattr(ic, "_autofill_platform_material_metadata", lambda **_kwargs: [])
    monkeypatch.setattr(ic, "_validate_platform_material_ready", lambda _material: [])

    result = ic._run_material_self_healing(
        packaging={"platforms": {}},
        platform_materials=[
            {
                "key": "wechat-channels",
                "label": "视频号",
                "blocking_reasons": [],
                "cover_path": "",
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "platform_specific_overrides": {},
            }
        ],
    )

    assert result["status"] == "manual_handoff"
    assert result["passes"][0]["status"] == "manual_handoff"
    assert result["passes"][0]["one_click_publish_ready"] is False
    assert result["final_contract"]["status"] == "manual_handoff"


def test_material_self_healing_defaults_to_explicit_collection_skip_for_supported_platforms(monkeypatch) -> None:
    monkeypatch.setattr(ic, "_validate_platform_material_ready", lambda _material: [])

    result = ic._run_material_self_healing(
        packaging={"platforms": {"douyin": {}}},
        platform_materials=[
            {
                "key": "douyin",
                "label": "抖音",
                "cover_path": "E:/covers/douyin.jpg",
                "blocking_reasons": [],
                "visibility_or_publish_mode": "draft",
                "scheduled_publish_at": "",
                "platform_specific_overrides": {},
            }
        ],
        requested_platforms=["douyin"],
    )

    assert result["status"] == "passed"
    assert result["final_contract"]["platforms"]["douyin"]["collection_policy_ready"] is True
    assert result["final_contract"]["platforms"]["douyin"]["publication_metadata_ready"] is True
    overrides = result["passes"][0]["applied_actions"]
    assert any(action["action"] == "defaulted_to_explicit_collection_skip" for action in overrides)


def test_material_result_payload_uses_hyphenated_external_platform_key() -> None:
    payload = ic._material_to_result_payload(
        {
            "key": "wechat_channels",
            "label": "视频号",
            "has_title": False,
            "title_label": "标题",
            "body_label": "简介",
            "tag_label": "标签",
            "constraints": {},
            "titles": [],
            "title_goals": [],
            "primary_title": "",
            "title_copy_all": "",
            "body": "正文",
            "tags": ["开箱"],
            "tags_copy": "#开箱",
            "full_copy": "正文\n#开箱",
            "cover_path": "",
            "publish_ready": False,
            "blocking_reasons": [],
        }
    )

    assert payload["key"] == "wechat-channels"


def test_material_result_payload_derives_publish_ready_from_preflight_when_flag_missing() -> None:
    payload = ic._material_to_result_payload(
        {
            "key": "douyin",
            "label": "抖音",
            "titles": ["标题"],
            "body": "正文",
            "tags": ["开箱"],
            "blocking_reasons": [],
            "live_publish_preflight": {
                "status": "blocked",
                "missing_required_surfaces": ["cover"],
            },
        }
    )

    assert payload["publish_ready"] is False


def test_packaging_from_existing_result_derives_publish_ready_from_preflight_when_flag_missing() -> None:
    packaging = ic._packaging_from_existing_intelligent_copy_result(
        {
            "platforms": [
                {
                    "key": "douyin",
                    "titles": ["标题"],
                    "body": "正文",
                    "tags": ["开箱"],
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["collection"],
                    },
                }
            ]
        },
        platform_keys=["douyin"],
    )

    assert packaging["platforms"]["douyin"]["publish_ready"] is False


def test_material_roundtrip_preserves_slot_and_collection_contract() -> None:
    payload = ic._material_to_result_payload(
        {
            "key": "xiaohongshu",
            "label": "小红书",
            "titles": ["标题"],
            "body": "正文",
            "tags": ["开箱"],
            "cover_path": "E:/covers/xhs.jpg",
            "blocking_reasons": [],
            "collection_name": "FAS新品",
            "scheduled_publish_slot": "18:00",
            "scheduled_publish_rationale": "晚高峰首发",
            "collection_management": {
                "status": "select_existing",
                "selected_collection_name": "FAS新品",
            },
            "available_collections": ["FAS新品", "EDC潮玩桌搭"],
            "collection_catalog": [{"name": "FAS新品", "selectable": True}],
            "platform_specific_overrides": {
                "group_chat_name": "F.A.S EDC畅聊群",
            },
        }
    )

    assert payload["scheduled_publish_slot"] == "18:00"
    assert payload["scheduled_publish_rationale"] == "晚高峰首发"
    assert payload["collection_management"]["selected_collection_name"] == "FAS新品"
    assert payload["available_collections"] == ["FAS新品", "EDC潮玩桌搭"]
    assert payload["collection_catalog"][0]["name"] == "FAS新品"


def test_packaging_and_targets_roundtrip_preserve_slot_and_collection_contract(tmp_path) -> None:
    packaging = ic._packaging_from_existing_intelligent_copy_result(
        {
            "platforms": [
                {
                    "key": "xiaohongshu",
                    "titles": ["标题"],
                    "body": "正文",
                    "tags": ["开箱"],
                    "collection_name": "FAS新品",
                    "scheduled_publish_slot": "18:00",
                    "scheduled_publish_rationale": "晚高峰首发",
                    "collection_management": {
                        "status": "select_existing",
                        "selected_collection_name": "FAS新品",
                    },
                    "available_collections": ["FAS新品", "EDC潮玩桌搭"],
                    "collection_catalog": [{"name": "FAS新品", "selectable": True}],
                }
            ]
        },
        platform_keys=["xiaohongshu"],
    )

    xhs = packaging["platforms"]["xiaohongshu"]
    assert xhs["scheduled_publish_slot"] == "18:00"
    assert xhs["scheduled_publish_rationale"] == "晚高峰首发"
    assert xhs["collection_management"]["selected_collection_name"] == "FAS新品"
    assert xhs["available_collections"] == ["FAS新品", "EDC潮玩桌搭"]

    targets = ic._build_publication_scheme_targets_from_packaging(
        packaging={"platforms": {"xiaohongshu": xhs}},
        existing_result={
            "platforms": [
                {
                    "key": "xiaohongshu",
                    "full_copy": "正文\n#开箱",
                    "copy_material": {"body": "正文"},
                }
            ]
        },
        material_dir=tmp_path,
        platform_keys=["xiaohongshu"],
    )

    assert targets[0]["scheduled_publish_slot"] == "18:00"
    assert targets[0]["scheduled_publish_rationale"] == "晚高峰首发"
    assert targets[0]["collection_name"] == "FAS新品"
    assert targets[0]["collection_management"]["selected_collection_name"] == "FAS新品"


def test_platform_packaging_export_preserves_slot_and_collection_contract() -> None:
    export_payload = ic._build_platform_packaging_export(
        packaging={"highlights": {}, "platforms": {}},
        platform_materials=[
            {
                "key": "xiaohongshu",
                "label": "小红书",
                "titles": ["标题"],
                "body": "正文",
                "tags": ["开箱"],
                "cover_path": "",
                "copy_material": {},
                "scheduled_publish_slot": "18:00",
                "scheduled_publish_rationale": "晚高峰首发",
                "collection_name": "FAS新品",
                "collection_management": {
                    "status": "select_existing",
                    "selected_collection_name": "FAS新品",
                },
                "available_collections": ["FAS新品", "EDC潮玩桌搭"],
                "collection_catalog": [{"name": "FAS新品", "selectable": True}],
            }
        ],
        requested_platforms=["xiaohongshu"],
    )

    xhs = export_payload["platforms"]["xiaohongshu"]
    assert xhs["scheduled_publish_slot"] == "18:00"
    assert xhs["scheduled_publish_rationale"] == "晚高峰首发"
    assert xhs["collection_management"]["selected_collection_name"] == "FAS新品"
    assert xhs["available_collections"] == ["FAS新品", "EDC潮玩桌搭"]


def test_platform_packaging_export_and_readback_normalize_wechat_platform_key(tmp_path) -> None:
    export_payload = ic._build_platform_packaging_export(
        packaging={"highlights": {}, "platforms": {}},
        platform_materials=[
            {
                "key": "wechat_channels",
                "label": "视频号",
                "titles": [],
                "body": "正文",
                "tags": ["开箱"],
                "cover_path": "",
                "copy_material": {},
            }
        ],
        requested_platforms=["wechat-channels"],
    )

    assert "wechat-channels" in export_payload["platforms"]
    assert "wechat_channels" not in export_payload["platforms"]

    roundtrip_packaging = ic._packaging_from_existing_intelligent_copy_result(
        {
            "platforms": [
                {
                    "key": "wechat-channels",
                    "titles": ["标题"],
                    "body": "正文",
                    "tags": ["开箱"],
                }
            ]
        },
        platform_keys=["wechat_channels"],
    )

    assert "wechat_channels" in roundtrip_packaging["platforms"]

    targets = ic._build_publication_scheme_targets_from_packaging(
        packaging={
            "platforms": {
                "wechat-channels": {
                    "primary_title": "标题",
                    "titles": ["标题"],
                    "body": "正文",
                    "tags": ["开箱"],
                }
            }
        },
        existing_result={
            "platforms": [
                {
                    "key": "wechat-channels",
                    "full_copy": "正文\n#开箱",
                    "copy_material": {"body": "正文"},
                }
            ]
        },
        material_dir=tmp_path,
        platform_keys=["wechat_channels"],
    )

    assert targets[0]["platform"] == "wechat-channels"


def test_build_publication_scheme_targets_from_packaging_falls_back_to_titles_when_primary_title_missing(tmp_path) -> None:
    targets = ic._build_publication_scheme_targets_from_packaging(
        packaging={
            "platforms": {
                "kuaishou": {
                    "titles": ["MAXACE美杜莎4双版本开箱，顶配和次顶配到底差在哪"],
                    "description": "折刀这东西关键看开合顺不顺、轴稳不稳。",
                    "tags": ["EDC折刀", "MAXACE美杜莎4", "开箱", "折刀"],
                }
            }
        },
        existing_result={"platforms": [{"key": "kuaishou"}]},
        material_dir=tmp_path,
        platform_keys=["kuaishou"],
    )

    assert targets[0]["title"] == "MAXACE美杜莎4双版本开箱，顶配和次顶配到底差在哪"


def test_load_existing_intelligent_copy_packaging_prefers_object_shape_platform_packaging(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "highlights": {"product": "MAXACE"},
                "platforms": {
                    "wechat-channels": {
                        "primary_title": "标题",
                        "description": "正文",
                        "live_publish_preflight": {"status": "ready"},
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "wechat_channels",
                        "primary_title": "旧标题",
                        "body": "旧正文",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    packaging = ic._load_existing_intelligent_copy_packaging(
        material_dir=material_dir,
        platform_keys=["wechat_channels"],
        fallback_result=ic._load_existing_intelligent_copy_result(material_dir),
    )

    assert packaging["highlights"]["product"] == "MAXACE"
    assert packaging["platforms"]["wechat_channels"]["primary_title"] == "标题"
    assert packaging["platforms"]["wechat_channels"]["live_publish_preflight"]["status"] == "ready"


def test_material_contract_blocks_stale_xiaohongshu_schedule_window() -> None:
    contract = ic._build_material_contract(
        [
            {
                "key": "xiaohongshu",
                "label": "小红书",
                "cover_path": "E:/covers/xhs.jpg",
                "blocking_reasons": [],
                "declaration": "原创声明",
                "collection_name": "EDC潮玩桌搭",
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-05-31T21:00",
                "platform_specific_overrides": {},
            }
        ]
    )

    assert contract["status"] == "failed"
    xhs = contract["platforms"]["xiaohongshu"]
    assert xhs["schedule_window_ready"] is False
    assert "schedule_window" in xhs["missing_fields"]
    assert xhs["schedule_window"]["reason"] == "schedule_too_soon"
    assert any("至少需要提前 60 分钟" in reason for reason in contract["blocking_reasons"])


def test_material_self_healing_refreshes_stale_xiaohongshu_schedule_window(monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(
        ppm,
        "_current_publication_platform_now",
        lambda: datetime(2026, 6, 1, 3, 21, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    packaging = {
        "platforms": {
            "xiaohongshu": {
                "scheduled_publish_at": "2026-05-31T21:00",
                "visibility_or_publish_mode": "scheduled",
                "collection_name": "EDC潮玩桌搭",
                "declaration": "原创声明",
            }
        }
    }
    material = {
        "key": "xiaohongshu",
        "label": "小红书",
        "has_title": True,
        "titles": ["MAXACE美杜莎4到货了"],
        "primary_title": "MAXACE美杜莎4到货了",
        "body": "MAXACE美杜莎4到货了，上手先看细节。",
        "tags": ["MAXACE", "美杜莎4"],
        "full_copy": "MAXACE美杜莎4到货了\n\nMAXACE美杜莎4到货了，上手先看细节。",
        "cover_path": "D:/material/smart-copy/01-xiaohongshu-cover.jpg",
        "copy_material": {},
        "collection_name": "EDC潮玩桌搭",
        "declaration": "原创声明",
        "visibility_or_publish_mode": "scheduled",
        "scheduled_publish_at": "2026-05-31T21:00",
        "blocking_reasons": [],
    }

    validation = ic._run_material_self_healing(
        packaging=packaging,
        platform_materials=[material],
    )

    assert validation["status"] == "passed"
    assert material["scheduled_publish_at"] == "2026-06-01T21:00"
    assert any(action["field"] == "scheduled_publish_at" for action in validation["passes"][0]["applied_actions"])
    assert validation["final_contract"]["platforms"]["xiaohongshu"]["schedule_window_ready"] is True


def test_upgrade_existing_intelligent_copy_result_persists_live_publish_preflight_into_contract(tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "00-cover-portrait_3_4.jpg").write_bytes(b"cover-34")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "话题",
                        "constraints": {"title_limit": 20, "body_limit": 1000, "tag_limit": 8, "tag_style": "hashtags_space"},
                        "titles": ["新到的美杜莎4"],
                        "primary_title": "新到的美杜莎4",
                        "title_copy_all": "1. 新到的美杜莎4",
                        "body": "两款配置一起到手，先看差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。\n\n#MAXACE #美杜莎4",
                        "cover_path": str(material_dir / "00-cover-portrait_3_4.jpg"),
                        "publish_ready": True,
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["xiaohongshu"],
        platform_options={
            "xiaohongshu": {
                "scheduled_publish_at": "2026-06-01T21:00",
                "visibility_or_publish_mode": "scheduled",
                "live_publish_preflight": {
                    "policy": "block_final_publish_when_required_surface_missing",
                    "status": "blocked",
                    "summary": "缺少定时发布面",
                    "missing_required_surfaces": ["schedule"],
                },
                "platform_specific_overrides": {
                    "selected_declarations": ["原创声明"],
                },
            }
        },
    )

    xhs = result["platforms"][0]
    assert xhs["live_publish_preflight"]["status"] == "blocked"
    assert xhs["publish_ready"] is False
    assert result["material_contract"]["status"] == "failed"
    assert result["material_contract"]["one_click_publish_ready"] is False
    assert result["material_contract"]["platforms"]["xiaohongshu"]["live_publish_preflight_ready"] is False

    exported = json.loads((material_dir / "platform-packaging.json").read_text(encoding="utf-8"))
    assert exported["platforms"]["xiaohongshu"]["live_publish_preflight"]["status"] == "blocked"


def test_upgrade_existing_intelligent_copy_result_preserves_object_shape_platform_packaging_metadata(tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "00-cover-portrait_3_4.jpg").write_bytes(b"cover-34")

    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "话题",
                        "constraints": {"title_limit": 20, "body_limit": 1000, "tag_limit": 8, "tag_style": "hashtags_space"},
                        "titles": ["新到的美杜莎4"],
                        "primary_title": "新到的美杜莎4",
                        "title_copy_all": "1. 新到的美杜莎4",
                        "body": "两款配置一起到手，先看差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。\n\n#MAXACE #美杜莎4",
                        "cover_path": str(material_dir / "00-cover-portrait_3_4.jpg"),
                        "publish_ready": True,
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "highlights": {"product": "MAXACE"},
                "platforms": {
                    "xiaohongshu": {
                        "primary_title": "新到的美杜莎4",
                        "description": "两款配置一起到手，先看差别。",
                        "collection_name": "EDC潮玩桌搭",
                        "live_publish_preflight": {
                            "status": "blocked",
                            "summary": "缺少定时发布面",
                            "missing_required_surfaces": ["schedule"],
                        },
                        "platform_specific_overrides": {
                            "selected_declarations": ["原创声明"],
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["xiaohongshu"],
    )

    exported = json.loads((material_dir / "platform-packaging.json").read_text(encoding="utf-8"))
    assert exported["highlights"]["product"] == "MAXACE"
    assert exported["platforms"]["xiaohongshu"]["collection_name"] == "EDC潮玩桌搭"
    assert exported["platforms"]["xiaohongshu"]["live_publish_preflight"]["status"] == "blocked"
    assert exported["platforms"]["xiaohongshu"]["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]


def test_material_contract_terminal_status_prefers_explicit_failed_over_stale_one_click_publish_ready_true() -> None:
    assert ic._material_contract_terminal_status(
        {
            "status": "failed",
            "one_click_publish_ready": True,
        }
    ) == "failed"


def test_material_contract_terminal_status_derives_failed_from_platform_statuses_when_root_status_missing() -> None:
    assert ic._material_contract_terminal_status(
        {
            "one_click_publish_ready": True,
            "platforms": {
                "douyin": {
                    "status": "failed",
                    "one_click_publish_ready": True,
                }
            },
        }
    ) == "failed"


def test_material_contract_terminal_status_derives_failed_from_blocking_reasons_when_root_status_missing() -> None:
    assert ic._material_contract_terminal_status(
        {
            "one_click_publish_ready": True,
            "blocking_reasons": ["缺少 live_publish_preflight"],
        }
    ) == "failed"


def test_material_contract_terminal_status_derives_manual_handoff_from_manual_handoff_platforms_when_root_status_missing() -> None:
    assert ic._material_contract_terminal_status(
        {
            "one_click_publish_ready": True,
            "manual_handoff_platforms": [
                {
                    "platform": "wechat-channels",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
        }
    ) == "manual_handoff"


def test_material_contract_terminal_status_prefers_manual_handoff_over_stale_root_blocking_reasons_when_one_click_ready() -> None:
    assert ic._material_contract_terminal_status(
        {
            "one_click_publish_ready": True,
            "blocking_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
            "manual_handoff_platforms": [
                {
                    "platform": "wechat-channels",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
        }
    ) == "manual_handoff"


def test_upgrade_existing_intelligent_copy_result_uses_cached_publication_scheme(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "00-cover-portrait_3_4.jpg").write_bytes(b"cover-34")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "话题",
                        "constraints": {"title_limit": 20, "body_limit": 1000, "tag_limit": 8, "tag_style": "hashtags_space"},
                        "titles": ["新到的美杜莎4"],
                        "primary_title": "新到的美杜莎4",
                        "title_copy_all": "1. 新到的美杜莎4",
                        "body": "两款配置一起到手，先看差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。\n\n#MAXACE #美杜莎4",
                        "cover_generation": {
                            "publish_ready": False,
                            "blocking_reasons": ["封面图像生成未完成"],
                            "cover_group": {"cover_path": str(material_dir / "00-cover-portrait_3_4.jpg")},
                        },
                        "publish_ready": False,
                        "blocking_reasons": ["封面图像生成未完成"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ic,
        "build_cached_publication_scheme",
        lambda **_kwargs: {
            "platform_options": {
                "xiaohongshu": {
                    "scheduled_publish_at": "2026-06-01T21:00",
                    "visibility_or_publish_mode": "scheduled",
                    "collection_name": "EDC潮玩桌搭",
                    "platform_specific_overrides": {
                        "selected_declarations": ["原创声明"],
                    },
                }
            }
        },
    )

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["xiaohongshu"],
        creator_profile_id="profile-1",
        creator_profile_name="FAS",
        browser="chrome",
    )

    assert result["material_contract"]["one_click_publish_ready"] is True
    payload = json.loads(smart_copy_path.read_text(encoding="utf-8"))
    assert payload["platforms"][0]["declaration"] == "原创声明"
    assert payload["platforms"][0]["collection_name"] == "EDC潮玩桌搭"


def test_upgrade_existing_intelligent_copy_result_uses_persisted_creator_context_for_cached_publication_scheme(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "00-cover-portrait_3_4.jpg").write_bytes(b"cover-34")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "creator_profile_id": "profile-1",
                "creator_profile_name": "FAS",
                "publication_context": {
                    "creator_profile_id": "profile-1",
                    "creator_profile_name": "FAS",
                },
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "label": "小红书",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "话题",
                        "constraints": {"title_limit": 20, "body_limit": 1000, "tag_limit": 8, "tag_style": "hashtags_space"},
                        "titles": ["新到的美杜莎4"],
                        "primary_title": "新到的美杜莎4",
                        "title_copy_all": "1. 新到的美杜莎4",
                        "body": "两款配置一起到手，先看差别。",
                        "tags": ["MAXACE", "美杜莎4"],
                        "tags_copy": "#MAXACE #美杜莎4",
                        "full_copy": "新到的美杜莎4\n\n两款配置一起到手，先看差别。\n\n#MAXACE #美杜莎4",
                        "cover_generation": {
                            "publish_ready": False,
                            "blocking_reasons": ["封面图像生成未完成"],
                            "cover_group": {"cover_path": str(material_dir / "00-cover-portrait_3_4.jpg")},
                        },
                        "publish_ready": False,
                        "blocking_reasons": ["封面图像生成未完成"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    def fake_cached_scheme(**kwargs):
        captured["creator_profile_id"] = kwargs.get("creator_profile_id")
        captured["creator_profile_name"] = kwargs.get("creator_profile_name")
        return {
            "platform_options": {
                "xiaohongshu": {
                    "scheduled_publish_at": "2026-06-01T21:00",
                    "visibility_or_publish_mode": "scheduled",
                    "collection_name": "EDC潮玩桌搭",
                    "platform_specific_overrides": {
                        "selected_declarations": ["原创声明"],
                    },
                }
            }
        }

    monkeypatch.setattr(ic, "build_cached_publication_scheme", fake_cached_scheme)

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["xiaohongshu"],
        browser="chrome",
    )

    assert captured["creator_profile_id"] == "profile-1"
    assert captured["creator_profile_name"] == "FAS"
    assert result["creator_profile_id"] == "profile-1"
    assert result["creator_profile_name"] == "FAS"
    assert result["publication_context"]["creator_profile_id"] == "profile-1"
    assert result["material_contract"]["one_click_publish_ready"] is True


def test_upgrade_existing_intelligent_copy_result_accepts_publication_scheme_file(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "MOT 风灵音叉推牌 锆合金版本"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "01-bilibili-cover.jpg").write_bytes(b"cover")

    smart_copy_path = material_dir / "smart-copy.json"
    smart_copy_path.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "csv"},
                        "titles": ["锆合金版风灵音叉推牌来了，质感真不一样"],
                        "primary_title": "锆合金版风灵音叉推牌来了，质感真不一样",
                        "title_copy_all": "1. 锆合金版风灵音叉推牌来了，质感真不一样",
                        "body": "到手最直接的感受就是扎实，锆合金版本更沉更稳。",
                        "tags": ["MOT风灵", "音叉推牌", "EDC玩具"],
                        "tags_copy": "MOT风灵, 音叉推牌, EDC玩具",
                        "full_copy": "锆合金版风灵音叉推牌来了，质感真不一样\n\n到手最直接的感受就是扎实，锆合金版本更沉更稳。",
                        "cover_path": str(material_dir / "01-bilibili-cover.jpg"),
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    scheme_path = tmp_path / "formal-live-scheme.json"
    scheme_path.write_text(
        json.dumps(
            {
                "platform_options": {
                    "bilibili": {
                        "scheduled_publish_at": "2026-06-02T19:30",
                        "visibility_or_publish_mode": "scheduled",
                        "category": "户外潮流",
                        "platform_specific_overrides": {
                            "selected_declarations": ["原创"],
                        },
                    }
                },
                "items": [
                    {
                        "platform": "bilibili",
                        "collection_management": {
                            "status": "needs_create",
                            "target_collection_name": "EDC潮玩桌搭",
                        },
                        "selected_options": {
                            "selected_declarations": ["原创"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    called = {"cached": False}

    def fake_cached_scheme(**_kwargs):
        called["cached"] = True
        return {}

    monkeypatch.setattr(ic, "build_cached_publication_scheme", fake_cached_scheme)

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["bilibili"],
        publication_scheme_path=str(scheme_path),
        browser="chrome",
    )

    assert called["cached"] is False
    assert result["status"] == "passed"
    assert result["publish_ready"] is True
    assert result["material_contract"]["platforms"]["bilibili"]["publication_metadata_ready"] is True
    assert result["material_contract"]["platforms"]["bilibili"]["collection_policy_ready"] is True

    payload = json.loads(smart_copy_path.read_text(encoding="utf-8"))
    material = payload["platforms"][0]
    assert material["declaration"] == "原创"
    assert material["category"] == "户外潮流"
    assert material["visibility_or_publish_mode"] == "scheduled"
    assert material["scheduled_publish_at"] == "2026-06-02T19:30"
    assert material["platform_specific_overrides"]["collection_management"]["target_collection_name"] == "EDC潮玩桌搭"


def test_upgrade_existing_intelligent_copy_result_prefers_publication_scheme_path_when_inline_scheme_is_empty(
    monkeypatch,
    tmp_path,
) -> None:
    source_dir = tmp_path / "MOT 风灵音叉推牌 锆合金版本"
    material_dir = source_dir / "smart-copy"
    material_dir.mkdir(parents=True)
    (material_dir / "01-bilibili-cover.jpg").write_bytes(b"cover")

    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "bilibili",
                        "label": "B站",
                        "has_title": True,
                        "title_label": "标题",
                        "body_label": "正文",
                        "tag_label": "标签",
                        "constraints": {"title_limit": 80, "body_limit": 250, "tag_limit": 10, "tag_style": "csv"},
                        "titles": ["锆合金版风灵音叉推牌来了"],
                        "primary_title": "锆合金版风灵音叉推牌来了",
                        "title_copy_all": "1. 锆合金版风灵音叉推牌来了",
                        "body": "到手最直接的感受就是扎实。",
                        "tags": ["MOT风灵", "音叉推牌"],
                        "tags_copy": "MOT风灵, 音叉推牌",
                        "full_copy": "锆合金版风灵音叉推牌来了\n\n到手最直接的感受就是扎实。\n\nMOT风灵, 音叉推牌",
                        "cover_path": str(material_dir / "01-bilibili-cover.jpg"),
                        "blocking_reasons": [],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    scheme_path = tmp_path / "formal-live-scheme.json"
    scheme_path.write_text(
        json.dumps(
            {
                "platform_options": {
                    "bilibili": {
                        "scheduled_publish_at": "2026-06-02T19:30",
                        "visibility_or_publish_mode": "scheduled",
                        "category": "户外潮流",
                    }
                },
                "items": [
                    {
                        "platform": "bilibili",
                        "collection_management": {
                            "status": "needs_create",
                            "target_collection_name": "EDC潮玩桌搭",
                        },
                        "selected_options": {
                            "selected_declarations": ["原创"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ic, "build_cached_publication_scheme", lambda **_kwargs: {})

    result = ic.upgrade_existing_intelligent_copy_result(
        str(source_dir),
        platforms=["bilibili"],
        publication_scheme={},
        publication_scheme_path=str(scheme_path),
        browser="chrome",
    )

    assert result["status"] == "passed"
    assert result["material_contract"]["platforms"]["bilibili"]["collection_policy_ready"] is True


@pytest.mark.asyncio
async def test_upgrade_folder_materials_route_passes_publication_scheme_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        intelligent_copy_api,
        "_resolve_generation_creator_profile",
        lambda _creator_profile_id: {"display_name": "FAS"},
    )

    def fake_upgrade(folder_path: str, **kwargs):
        captured["folder_path"] = folder_path
        captured.update(kwargs)
        return {
            "status": "passed",
            "folder_path": folder_path,
            "material_dir": f"{folder_path}/smart-copy",
            "platforms": [],
            "material_contract": {"status": "passed", "one_click_publish_ready": True, "platforms": {}},
            "material_validation": {"status": "passed"},
            "publish_ready": True,
            "blocking_reasons": [],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
        }

    monkeypatch.setattr(intelligent_copy_api, "upgrade_existing_intelligent_copy_result", fake_upgrade)

    body = intelligent_copy_api.IntelligentCopyUpgradeIn(
        folder_path="E:/materials/demo",
        platforms=["bilibili"],
        creator_profile_id="profile-1",
        browser="chrome",
        publication_scheme_path="E:/schemes/formal-live-scheme.json",
    )

    result = await intelligent_copy_api.upgrade_folder_materials(body)

    assert result["status"] == "passed"
    assert captured["folder_path"] == "E:/materials/demo"
    assert captured["platforms"] == ["bilibili"]
    assert captured["publication_scheme_path"] == "E:/schemes/formal-live-scheme.json"
    assert captured["creator_profile_id"] == "profile-1"
    assert captured["creator_profile_name"] == "FAS"


@pytest.mark.asyncio
async def test_generate_folder_materials_route_passes_creator_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}
    creator_profile = {
        "display_name": "FAS",
        "creator_profile": {
            "publishing": {
                "publication_rules": [
                    {"type": "preferred_collection", "platforms": ["bilibili"], "preferred_collection_name": "FAS新品"}
                ]
            }
        },
    }

    monkeypatch.setattr(
        intelligent_copy_api,
        "_resolve_generation_creator_profile",
        lambda _creator_profile_id: creator_profile,
    )

    async def fake_generate(folder_path: str, **kwargs):
        captured["folder_path"] = folder_path
        captured.update(kwargs)
        return {
            "status": "passed",
            "folder_path": folder_path,
            "material_dir": f"{folder_path}/smart-copy",
            "platforms": [],
            "material_contract": {"status": "passed", "one_click_publish_ready": True, "platforms": {}},
            "material_validation": {"status": "passed"},
            "publish_ready": True,
            "blocking_reasons": [],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
        }

    monkeypatch.setattr(intelligent_copy_api, "generate_intelligent_copy", fake_generate)

    body = intelligent_copy_api.IntelligentCopyGenerateIn(
        folder_path="E:/materials/demo",
        platforms=["bilibili"],
        creator_profile_id="profile-1",
    )

    result = await intelligent_copy_api.generate_folder_materials(body)

    assert result["status"] == "passed"
    assert captured["folder_path"] == "E:/materials/demo"
    assert captured["creator_profile_id"] == "profile-1"
    assert captured["creator_profile_name"] == "FAS"
    assert captured["creator_profile"] == creator_profile


@pytest.mark.asyncio
async def test_render_platform_cover_falls_back_to_reference_cover_after_single_codex_attempt(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    calls = {"count": 0}

    async def fake_generate_edited_cover_image(**_kwargs):
        calls["count"] += 1
        raise TimeoutError("codex imagegen timed out after 30s and no generated image was found")

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", lambda source_path, output_path, width, height, fit_mode: output_path.write_bytes(b"fallback-cover"))
    monkeypatch.setattr(ic, "get_settings", lambda: SimpleNamespace(
        intelligent_copy_cover_image_generation_enabled=True,
        intelligent_copy_cover_codex_max_attempts=1,
    ))

    result = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MAXACE美杜莎4到货了",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        cover_brief={
            "video_type": "开箱体验",
            "product_identity": "MAXACE 美杜莎4",
            "selling_angle": "顶配次顶配对比",
            "visual_brief": "主体真实，标题居中。",
        },
    )

    assert calls["count"] == 1
    assert result["publish_ready"] is False
    assert "封面包装生图未完成" in result["blocking_reasons"][0]
    assert "已回退使用参考帧封面" in result["warnings"][0]
    assert output.read_bytes() == b"fallback-cover"
