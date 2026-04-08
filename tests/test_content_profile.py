from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roughcut.edit.presets import get_workflow_preset
import pytest

from roughcut.review.content_profile import (
    _merge_specific_profile_hints,
    _aggregate_visual_profile_hints,
    _apply_visual_subject_guard,
    _probe_duration,
    _build_conservative_identity_summary,
    _coerce_subject_type_to_supported_main_type,
    _build_profile_summary,
    _extract_reference_frames,
    _infer_visual_profile_hints,
    _sanitize_profile_identity,
    _seed_profile_from_text,
    _build_search_queries,
    _filter_evidence_by_visual_subject,
    _fallback_profile,
    _seed_profile_from_subtitles,
    _seed_profile_from_user_memory,
    assess_content_profile_automation,
    apply_identity_review_guard,
    apply_content_profile_feedback,
    build_content_profile_cache_fingerprint,
    build_reviewed_transcript_excerpt,
    build_review_feedback_search_queries,
    build_transcript_excerpt,
    build_cover_title,
    enrich_content_profile,
    infer_content_profile,
    polish_subtitle_items,
)


def test_build_cover_title_avoids_generic_main_line():
    preset = get_workflow_preset("unboxing_standard")
    title = build_cover_title(
        {
            "subject_brand": "曼（MAN）",
            "subject_model": "工具钳（具体型号未知）",
            "subject_type": "多功能工具钳",
            "video_theme": "产品开箱与上手体验",
            "hook_line": "",
        },
        preset,
    )

    assert title["top"] == "MAN"
    assert title["main"] == "MAN多功能工具钳"
    assert title["bottom"] == "这次升级够不够狠"


def test_probe_duration_uses_configured_ffmpeg_timeout(monkeypatch: pytest.MonkeyPatch):
    import roughcut.review.content_profile as content_profile_mod
    import subprocess

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout=b'{"format":{"duration":"12.3"}}')

    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: SimpleNamespace(ffmpeg_timeout_sec=45))
    monkeypatch.setattr(subprocess, "run", fake_run)

    duration = _probe_duration(Path("demo.mp4"))

    assert duration == 12.3
    assert captured["timeout"] == 45


def test_build_content_profile_cache_fingerprint_uses_infer_version_without_seeded_profile():
    fingerprint = build_content_profile_cache_fingerprint(
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_file_hash="demo-hash",
        workflow_template="",
        transcript_excerpt="[0.8-3.0] 大家好欢迎来到我的。\n[3.7-5.4] 播数字人播客测试现场。",
        glossary_terms=[],
        user_memory={},
        include_research=False,
        copy_style="attention_grabbing",
    )

    assert fingerprint["version"].startswith("2026-04-04.infer.v34")
    assert fingerprint["seeded_profile_sha256"] == ""


@pytest.mark.asyncio
async def test_infer_content_profile_routes_visual_semantic_evidence_into_content_understanding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_schema import ContentUnderstanding

    captured: dict[str, object] = {}

    async def fake_infer_content_understanding(evidence_bundle):
        captured["evidence_bundle"] = evidence_bundle
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="机能双肩包",
            video_theme="机能双肩包展示",
            summary="视频主要展示机能双肩包。",
            hook_line="机能包展示",
            engagement_question="你更在意背负还是结构？",
            search_queries=["机能双肩包"],
            needs_review=True,
            review_reasons=["待人工复核"],
        )

    monkeypatch.setattr(content_profile_module, "infer_content_understanding", fake_infer_content_understanding)
    monkeypatch.setattr(content_profile_module, "_extract_reference_frames", lambda *args, **kwargs: [tmp_path / "f1.jpg"])
    monkeypatch.setattr(
        content_profile_module,
        "resolve_content_understanding_capabilities",
        lambda **kwargs: {"visual_understanding": {"provider": "minimax", "mode": "native_multimodal", "status": "ready"}},
    )
    async def fake_infer_visual_semantic_evidence(frame_paths, capabilities):
        return {
            "object_categories": ["backpack"],
            "subject_candidates": ["机能双肩包"],
            "visible_brands": ["HSJUN"],
        }

    monkeypatch.setattr(content_profile_module, "infer_visual_semantic_evidence", fake_infer_visual_semantic_evidence)
    monkeypatch.setattr(
        content_profile_module,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_enabled=False,
            active_reasoning_provider="minimax",
            reasoning_provider="minimax",
        ),
    )

    await infer_content_profile(
        source_path=tmp_path / "bag.mp4",
        source_name="bag.mp4",
        subtitle_items=[],
        include_research=False,
    )

    evidence_bundle = captured["evidence_bundle"]
    assert evidence_bundle["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert evidence_bundle["visual_semantic_evidence"]["visible_brands"] == ["HSJUN"]


@pytest.mark.asyncio
async def test_infer_content_profile_runs_research_when_semantic_fact_expansions_exist_without_final_queries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    captured_queries: list[str] = []

    async def fake_infer_content_understanding(evidence_bundle):
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="flashlight",
            primary_subject="SLIM2代ULTRA手电筒",
            semantic_facts=ContentSemanticFacts(
                search_expansions=["SLIM2 ULTRA", "SLIM2 PRO", "SLIM2代ULTRA版本"]
            ),
            subject_entities=[SubjectEntity(kind="product", name="SLIM2代ULTRA手电筒")],
            search_queries=[],
            video_theme="手电筒选购与保值性对比",
            summary="视频围绕 SLIM2代ULTRA手电筒展开选购对比。",
            hook_line="手电版本怎么选",
            engagement_question="你更在意保值还是亮度？",
            needs_review=True,
        )

    async def fake_build_hybrid_verification_bundle(*, search_queries, online_search=None, internal_search=None, session=None):
        captured_queries.extend(search_queries)
        return SimpleNamespace(search_queries=list(search_queries), online_results=[], database_results=[])

    async def fake_verify_content_understanding(*, understanding, evidence_bundle, verification_bundle):
        return understanding

    monkeypatch.setattr(content_profile_module, "infer_content_understanding", fake_infer_content_understanding)
    monkeypatch.setattr(content_profile_module, "build_hybrid_verification_bundle", fake_build_hybrid_verification_bundle)
    monkeypatch.setattr(content_profile_module, "verify_content_understanding", fake_verify_content_understanding)
    monkeypatch.setattr(content_profile_module, "_extract_reference_frames", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        content_profile_module,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_enabled=False,
            active_reasoning_provider="minimax",
            reasoning_provider="minimax",
        ),
    )

    await infer_content_profile(
        source_path=tmp_path / "flashlight.mp4",
        source_name="flashlight.mp4",
        subtitle_items=[],
        include_research=True,
    )

    assert captured_queries == ["SLIM2 ULTRA", "SLIM2 PRO", "SLIM2代ULTRA版本"]


def test_build_reviewed_transcript_excerpt_applies_accepted_corrections():
    excerpt = build_reviewed_transcript_excerpt(
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "这次开箱的是锐特的旧型号",
                "text_norm": "这次开箱的是锐特的旧型号",
                "text_final": "这次开箱的是锐特的旧型号",
            },
            {
                "index": 1,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "后面重点看开合手感",
                "text_norm": "后面重点看开合手感",
                "text_final": "后面重点看开合手感",
            },
        ],
        [
            {"item_index": 0, "original": "锐特", "accepted": "REATE"},
            {"item_index": 0, "original": "旧型号", "accepted": "EXO-M"},
        ],
    )

    assert "REATE" in excerpt
    assert "EXO-M" in excerpt
    assert "锐特" not in excerpt


def test_build_review_keywords_preserves_mixed_chinese_latin_product_tokens_and_downranks_noise():
    from roughcut.review.content_profile import _build_review_keywords

    keywords = _build_review_keywords(
        {
            "subject_brand": "DJI",
            "subject_model": "Mini 4 Pro",
            "subject_type": "无人机",
            "video_theme": "DJI Mini 4 Pro 开箱评测",
            "visible_text": "DJI Mini 4 Pro",
            "transcript_excerpt": "这次是 DJI Mini 4 Pro 开箱评测。",
            "search_queries": ["开箱", "评测", "DJI Mini 4 Pro", "dji mini 4 pro"],
        }
    )

    mixed_token_matches = [token for token in keywords if token.replace(" ", "").casefold() == "djimini4pro"]
    assert len(mixed_token_matches) == 1
    assert "开箱" not in keywords
    assert "评测" not in keywords
    if any(token in {"DJI", "Mini 4 Pro"} for token in keywords):
        mixed_index = keywords.index(mixed_token_matches[0])
        split_indexes = [keywords.index(token) for token in ("DJI", "Mini 4 Pro") if token in keywords]
        assert mixed_index < min(split_indexes)


def test_seed_profile_from_text_extracts_flashlight_brand_and_model():
    seeded = _seed_profile_from_text("陆虎SK零五二代Pro UV版手电筒开箱，对比一代的变化。")

    assert seeded["subject_brand"] == "Loop露普"
    assert seeded["subject_model"] == "SK05二代ProUV版"
    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert seeded["video_theme_candidates"] == ["Loop露普SK05二代ProUV版开箱与一代对比评测"]
    assert any("SK05" in item for item in seeded["search_queries"])


def test_seed_profile_from_text_extracts_olight_slim2_ultra_identity():
    seeded = _seed_profile_from_text(
        "今天想说到一个新的手机筒，是奥雷SLIM2代的ULTRA版本。"
        "本来我是想买那个PRO版的，但最后还是选了ULTRA。"
    )

    assert seeded["subject_brand"] == "OLIGHT"
    assert seeded["subject_model"] == "SLIM2代ULTRA版本"
    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert any("OLIGHT" in item for item in seeded["search_queries"])


def test_seed_profile_from_text_keeps_physical_product_subject_when_stray_tech_brand_appears():
    seeded = _seed_profile_from_text(
        "这期主要开箱一个夜骑手电，重点看泛光、聚光和夹持手感。"
        "桌面显示器上挂着 ComfyUI 页面，但那不是本期主体。"
    )

    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert seeded.get("subject_brand", "") != "ComfyUI"


def test_seed_profile_from_text_does_not_turn_flashlight_unboxing_into_comfyui_tool():
    seeded = _seed_profile_from_text(
        "这次开箱 Loop露普 SK05二代Pro UV版手电，重点看泛光、UV 和夜骑补光。"
        "桌面显示器只是挂着 ComfyUI 页面，不是这次要讲的主体。"
    )

    assert seeded["subject_brand"] == "Loop露普"
    assert seeded["subject_model"] == "SK05二代ProUV版"
    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert all("ComfyUI" not in item for item in seeded.get("video_theme_candidates", []))


def test_seed_profile_from_text_does_not_promote_late_uncorroborated_flashlight_model():
    seeded = _seed_profile_from_text(
        "这期主要开箱一个新的手电筒，前面重点讲 Pro、Slim 和 Ultra 版本差异。"
        "后面零散提到一个 SK05 的误识别片段，但没有品牌支撑，也不是本期主体。"
    )

    assert seeded.get("subject_brand", "") != "Loop露普"
    assert seeded.get("subject_model", "") == ""
    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert not any("SK05" in item for item in seeded.get("video_theme_candidates", []))
    assert not any("SK05" in item for item in seeded.get("search_queries", []))


def test_seed_profile_from_text_extracts_bag_brand_and_model_from_fxx1_alias():
    seeded = _seed_profile_from_text("这期鸿福 F叉二一小副包做个开箱测评，重点看分仓、挂点和日常收纳。")

    assert seeded["subject_brand"] == "狐蝠工业"
    assert seeded["subject_model"] == "FXX1小副包"
    assert seeded["subject_type_candidates"] == ["EDC机能包"]
    assert seeded["video_theme_candidates"] == ["狐蝠工业FXX1小副包开箱与上手评测"]
    assert any("FXX1小副包" in item for item in seeded["search_queries"])


def test_seed_profile_from_text_uses_glossary_brand_and_generic_model():
    seeded = _seed_profile_from_text(
        "今天开箱狐蝠工业 F21 小副包，主要看看分仓和挂点。",
        glossary_terms=[
            {
                "correct_form": "FOXBAT狐蝠工业",
                "wrong_forms": ["狐蝠工业", "FOXBAT"],
                "category": "bag_brand",
            }
        ],
    )

    assert seeded["subject_brand"] == "FOXBAT狐蝠工业"
    assert seeded["subject_model"] == "F21小副包"
    assert seeded["subject_type_candidates"] == ["EDC机能包"]
    assert any("F21" in item for item in seeded["search_queries"])


def test_seed_profile_from_text_uses_bag_hotwords_as_scoped_search_evidence():
    seeded = _seed_profile_from_text(
        "这次赫斯郡和船家的游刃机能包，重点看分仓、挂点和背负调节。",
        glossary_terms=[
            {
                "correct_form": "HSJUN",
                "wrong_forms": ["hesijun", "赫斯郡", "赫斯俊", "hsjun"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
            },
            {
                "correct_form": "BOLTBOAT",
                "wrong_forms": ["Boltboat", "BOLT BOAT", "船家"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
            },
            {
                "correct_form": "游刃",
                "wrong_forms": [],
                "category": "bag_model",
                "domain": "bag",
                "category_scope": "bag",
            },
        ],
    )

    assert seeded.get("subject_brand", "") == ""
    assert seeded["subject_model"] == "游刃"
    assert seeded["subject_type_candidates"] == ["EDC机能包"]
    assert "HSJUN 游刃" in seeded["search_queries"]
    assert "BOLTBOAT 游刃" in seeded["search_queries"]


def test_seed_profile_from_text_extracts_foxbat_zhenfeng_backpack_identity():
    seeded = _seed_profile_from_text(
        "这次主要看狐蝠工业阵风机能双肩包，重点看背负、分仓和日常收纳。",
        glossary_terms=[
            {
                "correct_form": "狐蝠工业",
                "wrong_forms": ["FOXBAT", "Foxbat", "鸿福"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
            },
            {
                "correct_form": "阵风",
                "wrong_forms": ["震风", "阵峰"],
                "category": "bag_model",
                "domain": "bag",
                "category_scope": "bag",
            },
        ],
    )

    assert seeded["subject_brand"] == "狐蝠工业"
    assert seeded["subject_model"] == "阵风"
    assert seeded["subject_type_candidates"] == ["EDC机能包"]
    assert any("狐蝠工业 阵风" in item or "狐蝠工业阵风" in item for item in seeded["search_queries"])


def test_seed_profile_from_text_does_not_promote_bag_hotwords_outside_bag_context():
    seeded = _seed_profile_from_text(
        "这次主要聊手电的流明和泛光，顺嘴提了赫斯郡和船家，但主体还是 slim2 ultra。",
        glossary_terms=[
            {
                "correct_form": "HSJUN",
                "wrong_forms": ["hesijun", "赫斯郡", "赫斯俊", "hsjun"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
            },
            {
                "correct_form": "BOLTBOAT",
                "wrong_forms": ["Boltboat", "BOLT BOAT", "船家"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
            },
            {
                "correct_form": "游刃",
                "wrong_forms": [],
                "category": "bag_model",
                "domain": "bag",
                "category_scope": "bag",
            },
        ],
    )

    assert seeded.get("subject_brand", "") not in {"HSJUN", "BOLTBOAT"}
    assert seeded["subject_type_candidates"] == ["EDC手电"]
    assert all("HSJUN" not in item for item in seeded.get("search_queries", []))
    assert all("BOLTBOAT" not in item for item in seeded.get("search_queries", []))


def test_seed_profile_from_text_uses_bag_transcription_seeds_as_weak_search_queries_when_identity_missing():
    seeded = _seed_profile_from_text(
        "这次主要看这个机能双肩包的背负、分仓和日常收纳。",
        glossary_terms=[
            {
                "correct_form": "狐蝠工业",
                "wrong_forms": ["FOXBAT", "Foxbat", "鸿福"],
                "category": "bag_brand",
                "domain": "bag",
                "category_scope": "bag",
                "transcription_seed_templates": ["edc_tactical"],
            },
            {
                "correct_form": "阵风",
                "wrong_forms": ["震风", "阵峰"],
                "category": "bag_model",
                "domain": "bag",
                "category_scope": "bag",
                "transcription_seed_templates": ["edc_tactical"],
            },
            {
                "correct_form": "双肩包",
                "wrong_forms": ["双肩抱"],
                "category": "bag",
                "domain": "bag",
                "category_scope": "bag",
            },
        ],
    )

    assert seeded.get("subject_brand", "") == ""
    assert seeded.get("subject_model", "") == ""
    assert seeded["subject_type_candidates"] == ["EDC机能包"]
    assert "狐蝠工业 阵风" in seeded["search_queries"]
    assert "狐蝠工业 双肩包" in seeded["search_queries"]


def test_sanitize_profile_identity_backfills_supported_transcript_brand_and_model():
    sanitized = _sanitize_profile_identity(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC手电",
            "video_theme": "Loop露普EDC手电功能演示",
        },
        transcript_excerpt="[22.6-25.0] 陆虎SK零五二代。\n[47.4-51.5] UV版其实我用的是相当多的。",
        source_name="20260225-153519.mp4",
        memory_hints=None,
    )

    assert sanitized["subject_brand"] == "Loop露普"
    assert sanitized["subject_model"] == "SK05二代UV版"


def test_sanitize_profile_identity_does_not_backfill_brand_model_from_theme_without_current_evidence():
    sanitized = _sanitize_profile_identity(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC手电",
            "video_theme": "Loop露普SK05二代UV版开箱与一代对比评测",
        },
        transcript_excerpt="这次主要还是讲二代版本的变化。",
        source_name="20260225-153519.mp4",
        memory_hints=None,
    )

    assert sanitized["subject_brand"] == ""
    assert sanitized["subject_model"] == ""


def test_sanitize_profile_identity_prefers_current_video_evidence_over_conflicting_profile_identity():
    sanitized = _sanitize_profile_identity(
        {
            "subject_brand": "LEATHERMAN",
            "subject_model": "SK05二代Pro UV版",
            "subject_type": "EDC手电",
            "video_theme": "LEATHERMAN SK05二代Pro UV版开箱对比评测",
            "summary": "这次重点看 LEATHERMAN SK05二代Pro UV版 的升级。",
        },
        transcript_excerpt="这次主要看 Loop露普 SK05二代Pro UV版 的泛光、UV 和二代变化。Loop露普这一代的灯珠排列也变了。",
        source_name="Loop露普_SK05二代ProUV版_20260225-153519.mp4",
        memory_hints=None,
    )

    assert sanitized["subject_brand"] == "Loop露普"
    assert sanitized["subject_model"] == "SK05二代Pro UV版"
    assert "LEATHERMAN" not in sanitized["video_theme"]
    assert "LEATHERMAN" not in sanitized["summary"]


def test_merge_specific_profile_hints_only_merges_identity_and_queries():
    profile = {
        "preset_name": "edc_tactical",
        "subject_type": "开箱产品",
        "video_theme": "新品开箱评测",
    }

    _merge_specific_profile_hints(
        profile,
        {
            "subject_type": "EDC手电",
            "video_theme": "Loop露普SK05二代UV版开箱与一代对比评测",
            "search_queries": ["Loop露普 SK05二代UV版"],
        },
    )

    assert profile["subject_type"] == "开箱产品"
    assert profile["video_theme"] == "新品开箱评测"
    assert profile["search_queries"] == ["Loop露普 SK05二代UV版"]


def test_sanitize_profile_identity_does_not_infer_type_or_theme_by_default():
    sanitized = _sanitize_profile_identity(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "video_theme": "",
            "visible_text": "FOXBAT F21 小副包 开箱",
        },
        transcript_excerpt="今天开箱 FOXBAT 狐蝠工业 F21 小副包，重点看分仓和挂点。",
        source_name="f21.mp4",
        glossary_terms=[
            {
                "correct_form": "FOXBAT狐蝠工业",
                "wrong_forms": ["狐蝠工业", "FOXBAT"],
                "category": "bag_brand",
            }
        ],
        memory_hints=None,
    )

    assert sanitized["subject_brand"] == "FOXBAT狐蝠工业"
    assert sanitized["subject_model"] == "F21小副包"
    assert sanitized["subject_type"] == ""
    assert sanitized["video_theme"] == ""


def test_seed_profile_from_user_memory_uses_recent_brand_model_corrections():
    seeded = _seed_profile_from_user_memory(
        "这次重点看 Loop露普 SK05二代Pro UV版 的泛光和 UV 效果。",
        {
            "field_preferences": {
                "subject_brand": [{"value": "Loop露普", "count": 6}],
                "subject_model": [{"value": "SK05二代Pro UV版", "count": 8}],
                "subject_type": [{"value": "EDC手电", "count": 3}],
            },
            "recent_corrections": [
                {"field_name": "subject_brand", "corrected_value": "Loop露普"},
                {"field_name": "subject_model", "corrected_value": "SK05二代Pro UV版"},
            ],
            "phrase_preferences": [],
        },
    )

    assert seeded["subject_brand"] == "Loop露普"
    assert seeded["subject_model"] == "SK05二代Pro UV版"
    assert seeded["subject_type_candidates"] == ["EDC手电"]


def test_seed_profile_from_user_memory_does_not_inject_brand_model_without_current_token_hit():
    seeded = _seed_profile_from_user_memory(
        "这次重点看夜骑补光、夹持结构和防滚设计。",
        {
            "field_preferences": {
                "subject_brand": [{"value": "Loop露普", "count": 6}],
                "subject_model": [{"value": "SK05二代Pro UV版", "count": 8}],
                "subject_type": [{"value": "EDC手电", "count": 3}],
            },
            "recent_corrections": [
                {"field_name": "subject_brand", "corrected_value": "Loop露普"},
                {"field_name": "subject_model", "corrected_value": "SK05二代Pro UV版"},
            ],
            "phrase_preferences": [{"phrase": "Loop露普 SK05二代Pro UV版", "count": 4}],
        },
    )

    assert seeded == {}


def test_seed_profile_from_user_memory_uses_confirmed_entity_for_flashlight_contextual_alias_hit():
    seeded = _seed_profile_from_user_memory(
        "这次手电开箱主要看司令官2的 Ultra 版本、流明档位和夹持手感。",
        {
            "field_preferences": {},
            "recent_corrections": [],
            "phrase_preferences": [],
            "confirmed_entities": [
                {
                    "brand": "傲雷",
                    "model": "司令官2Ultra",
                    "phrases": ["傲雷司令官2Ultra", "司令官2Ultra"],
                    "model_aliases": [{"wrong": "司令官2", "correct": "司令官2Ultra"}],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ],
        },
    )

    assert seeded["subject_brand"] == "傲雷"
    assert seeded["subject_model"] == "司令官2Ultra"
    assert seeded["subject_type_candidates"] == ["EDC手电"]


def test_seed_profile_from_user_memory_uses_confirmed_entity_when_alias_and_variant_are_split():
    seeded = _seed_profile_from_user_memory(
        "今天我们收到一个新的手机筒。"
        "本来想买Pro版，这次是司令官2代的 Ultra 版本，材料和参数上有差。",
        {
            "field_preferences": {},
            "recent_corrections": [],
            "phrase_preferences": [],
            "confirmed_entities": [
                {
                    "brand": "傲雷",
                    "model": "司令官2Ultra",
                    "phrases": ["傲雷司令官2Ultra", "司令官2Ultra"],
                    "model_aliases": [{"wrong": "司令官2", "correct": "司令官2Ultra"}],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ],
        },
    )

    assert seeded["subject_brand"] == "傲雷"
    assert seeded["subject_model"] == "司令官2Ultra"
    assert seeded["subject_type_candidates"] == ["EDC手电"]


def test_seed_profile_from_user_memory_does_not_inject_confirmed_entity_outside_flashlight_context():
    seeded = _seed_profile_from_user_memory(
        "这次主要聊桌面灯光和拍摄布光，没有讲具体产品型号。",
        {
            "field_preferences": {},
            "recent_corrections": [],
            "phrase_preferences": [],
            "confirmed_entities": [
                {
                    "brand": "傲雷",
                    "model": "司令官2Ultra",
                    "phrases": ["傲雷司令官2Ultra", "司令官2Ultra"],
                    "model_aliases": [{"wrong": "司令官2", "correct": "司令官2Ultra"}],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ],
        },
    )

    assert seeded == {}


def test_build_cover_title_prefers_visible_english_brand():
    preset = get_workflow_preset("unboxing_upgrade")
    title = build_cover_title(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "战术钳",
            "video_theme": "",
            "visible_text": "LEATHERMAN SURGE",
            "hook_line": "",
        },
        preset,
    )

    assert title["top"] == "LEATHERMAN"
    assert title["main"] == "LEATHERMAN战术钳"


def test_build_cover_title_drops_edc_prefix_from_subject_type():
    preset = get_workflow_preset("edc_tactical")
    title = build_cover_title(
        {
            "subject_brand": "REATE",
            "subject_model": "",
            "subject_type": "EDC折刀",
            "video_theme": "折刀雕刻开箱",
            "hook_line": "REATE 这把雕刻折刀终于来了",
        },
        preset,
    )

    assert title["top"] == "REATE"
    assert title["main"] == "REATE折刀"


def test_build_cover_title_prefers_specific_ai_feature_anchor():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 无限画布新功能上线与实操演示",
            "hook_line": "RunningHub 刚上线无限画布，漫剧工作流终于顺了",
        },
        preset,
    )

    assert title["top"] == "RUNNINGHUB"
    assert title["main"] == "无限画布"
    assert title["bottom"] == "这功能强得离谱"


def test_build_cover_title_upgrades_software_hook_to_more_explosive_copy():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "工作流",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 工作流搭建与节点编排教程",
            "hook_line": "RunningHub 工作流教程",
        },
        preset,
    )

    assert title["bottom"] == "核心流程直接起飞"


def test_build_cover_title_respects_global_copy_style():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 无限画布新功能上线与实操演示",
            "copy_style": "trusted_expert",
        },
        preset,
    )

    assert title["bottom"] == "无限画布关键差异讲明白"


def test_build_cover_title_clears_duplicate_top_when_main_already_contains_model():
    preset = get_workflow_preset("edc_tactical")
    title = build_cover_title(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC折刀",
            "visible_text": "MT33",
            "video_theme": "MT33折刀细节展示与镜面板评测",
            "hook_line": "EDC折刀这次太炸了",
        },
        preset,
    )

    assert title["top"] == ""
    assert title["main"] == "MT33折刀"


def test_build_cover_title_prefers_theme_entity_anchor_for_product_titles():
    preset = get_workflow_preset("edc_tactical")
    title = build_cover_title(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC折刀",
            "video_theme": "NOC MT-33折刀细节展示与磁顶配镜面板评测",
            "visible_text": "MT33",
            "hook_line": "EDC折刀这次太炸了",
        },
        preset,
    )

    assert title["top"] == "NOC"
    assert title["main"] == "NOC MT-33折刀"


def test_build_cover_title_uses_transcript_focus_for_generic_unboxing_hook():
    preset = get_workflow_preset("unboxing_standard")
    title = build_cover_title(
        {
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "产品开箱与上手体验",
            "transcript_excerpt": "这次重点看锁定机构和开合手感，后面再看钳头结构。",
            "hook_line": "",
        },
        preset,
    )

    assert title["bottom"] == "锁定机构直接看"


def test_fallback_profile_does_not_use_timestamp_as_model():
    profile = _fallback_profile(
        source_name="20260130-140529.mp4",
        channel_profile=None,
        transcript_excerpt="",
    )

    assert profile["subject_model"] == ""
    assert "20260130-140529" not in profile["summary"]


def test_build_search_queries_ignores_timestamp_filename():
    queries = _build_search_queries(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "开箱产品",
            "search_queries": [],
        },
        "20260130-140529.mp4",
    )

    assert "20260130-140529" not in queries


def test_build_search_queries_uses_transcript_signal_terms_for_proactive_search():
    queries = _build_search_queries(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "多功能工具钳",
            "search_queries": [],
        },
        "20260130-140529.mp4",
        transcript_excerpt="[220.0-222.0] ARC 这把工具真的很顺手",
    )

    assert "ARC 开箱" in queries
    assert "ARC 多功能工具钳" in queries


def test_build_search_queries_prefers_ai_feature_anchor_for_software_topics():
    queries = _build_search_queries(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "search_queries": [],
        },
        "RH无限画布 快速漫剧.mp4",
        transcript_excerpt="[12.0-18.0] 今天 RunningHub 上线了无限画布功能，拿来做漫剧工作流。",
    )

    assert "RunningHub 无限画布" in queries
    assert "RunningHub 无限画布 教程" in queries
    assert "RunningHub 无限画布 漫剧" in queries


def test_build_search_queries_anchors_model_only_product_with_subject_type():
    queries = _build_search_queries(
        {
            "subject_brand": "",
            "subject_model": "MT33",
            "subject_type": "EDC折刀",
            "search_queries": [],
        },
        "VID_20260112_122408.mp4",
        transcript_excerpt="[12.0-18.0] 这次主要看 MT33 这把折刀的结构和反光细节。",
    )

    assert "MT33 EDC折刀" in queries
    assert "MT33 折刀" in queries
    assert "MT33 开箱" not in queries


def test_ensure_search_queries_rebuilds_deduped_fallback_queries_from_empty_search_query_list():
    from roughcut.review.content_profile import _ensure_search_queries

    profile = {
        "subject_type": "开箱",
        "content_kind": "unboxing",
        "search_queries": ["", " ", "\t"],
    }

    queries = _ensure_search_queries(
        profile,
        "开箱.mp4",
        transcript_excerpt="",
    )

    assert queries
    assert any("开箱" in query for query in queries)
    assert all(str(query).strip() for query in queries)
    assert len({query.strip() for query in queries}) == len(queries)


def test_apply_identity_review_guard_drops_stale_search_queries_without_current_support():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "video_theme": "版本差异与上手体验",
            "search_queries": ["ComfyUI 工作流 教程"],
            "transcript_excerpt": "今天看傲雷这支司令官2 Ultra 手电，重点对比 Pro 和 Slim 版本差异。",
        },
        source_name="Commander2Ultra-unboxing.mp4",
    )

    assert "ComfyUI 工作流 教程" not in guarded["search_queries"]


def test_apply_identity_review_guard_keeps_currently_supported_search_queries():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "video_theme": "版本差异与上手体验",
            "search_queries": ["傲雷 司令官2Ultra 对比"],
            "transcript_excerpt": "今天看傲雷这支司令官2 Ultra 手电，重点对比 Pro 和 Slim 版本差异。",
        },
        source_name="Commander2Ultra-unboxing.mp4",
    )

    assert "傲雷 司令官2Ultra 对比" in guarded["search_queries"]


def test_apply_identity_review_guard_clears_visible_text_that_conflicts_with_verified_identity():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "FOXBAT狐蝠工业",
            "subject_model": "F21小副包",
            "subject_type": "EDC机能包",
            "video_theme": "分仓挂点与上手体验",
            "visible_text": "WOLF F21",
            "transcript_excerpt": "这次主要看狐蝠工业 F21 小副包的分仓和挂点设计。",
        },
        source_name="foxbat-f21.mp4",
        glossary_terms=[
            {"correct_form": "FOXBAT狐蝠工业", "wrong_forms": ["狐蝠工业", "FOXBAT"], "category": "bag_brand"},
            {"correct_form": "F21小副包", "wrong_forms": ["F21", "F21 小副包"], "category": "bag_model"},
        ],
    )

    assert guarded["visible_text"] == ""


def test_apply_identity_review_guard_prefers_ocr_and_transcript_source_labels_over_graph_memory():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "video_theme": "旧型号上手体验",
            "summary": "主要看傲雷司令官2Ultra。",
            "transcript_excerpt": "这期主要看分仓和挂点设计。",
            "ocr_evidence": {
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "video_theme": "狐蝠工业FXX1小副包开箱与挂点评测",
                }
            },
        },
        user_memory={
            "confirmed_entities": [
                {
                    "brand": "傲雷",
                    "model": "司令官2Ultra",
                    "phrases": ["傲雷司令官2Ultra", "司令官2Ultra"],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ]
        },
        source_name="demo.mp4",
    )

    assert guarded["subject_brand"] == "狐蝠工业"
    assert guarded["subject_model"] == "FXX1小副包"
    assert guarded["subject_type"] == ""
    assert guarded["video_theme"] == ""


def test_apply_identity_review_guard_does_not_infer_type_or_theme_without_llm_understanding():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "video_theme": "",
            "summary": "",
            "transcript_excerpt": "这期主要看 VX07 机能包的装载和背负细节。",
            "ocr_evidence": {
                "visible_text": "VX07 机能包 开箱",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "赫斯俊",
                    "subject_model": "VX07",
                    "subject_type": "EDC机能包",
                    "video_theme": "VX07机能包开箱对比评测",
                }
            },
        },
        source_name="demo.mp4",
    )

    assert guarded["subject_brand"] == "赫斯俊"
    assert guarded["subject_model"] == "VX07"
    assert guarded["subject_type"] == ""
    assert guarded["video_theme"] == ""


def test_apply_identity_review_guard_drops_profile_only_specific_theme_without_current_support():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC机能包",
            "video_theme": "ComfyUI 无限画布工作流实操",
            "summary": "主要讲 ComfyUI 工作流。",
            "transcript_excerpt": "这期主要看分仓、挂点和日常收纳。",
            "ocr_evidence": {
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                }
            },
        },
        source_name="demo.mp4",
    )

    assert guarded["subject_brand"] == "狐蝠工业"
    assert guarded["subject_model"] == "FXX1小副包"
    assert guarded["video_theme"] == ""
    assert guarded["summary"] == ""


def test_apply_identity_review_guard_does_not_override_llm_understanding_identity():
    guarded = apply_identity_review_guard(
        {
            "subject_brand": "",
            "subject_model": "VX07",
            "subject_type": "EDC机能包",
            "video_theme": "VX07机能包开箱对比评测",
            "summary": "这条视频主要围绕 VX07 机能包的装载和背负体验展开。",
            "transcript_excerpt": "这期主要看 VX07 机能包的装载和背负细节。",
            "content_understanding": {
                "video_type": "unboxing",
                "content_domain": "gear",
                "primary_subject": "EDC机能包",
                "subject_entities": [
                    {
                        "kind": "product",
                        "name": "VX07机能包",
                        "brand": "",
                        "model": "VX07",
                    }
                ],
                "video_theme": "VX07机能包开箱对比评测",
                "summary": "这条视频主要围绕 VX07 机能包的装载和背负体验展开。",
                "hook_line": "实战向改版",
                "engagement_question": "你更在意装载还是背负？",
                "search_queries": ["VX07 机能包"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.74},
                "needs_review": False,
                "review_reasons": [],
            },
        },
        source_name="vx07.mp4",
        user_memory={
            "confirmed_entities": [
                {
                    "brand": "Loop露普",
                    "model": "SK05二代Pro UV版",
                    "phrases": ["SK05", "手电"],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ]
        },
    )

    assert guarded["subject_model"] == "VX07"
    assert guarded["subject_type"] == "EDC机能包"
    assert guarded["video_theme"] == "VX07机能包开箱对比评测"
    assert guarded["summary"] == "这条视频主要围绕 VX07 机能包的装载和背负体验展开。"
    assert guarded["content_understanding"]["primary_subject"] == "EDC机能包"
    assert guarded["identity_review"]["required"] is False


def test_coerce_subject_type_to_supported_main_type_returns_canonical_main_type_empty_for_specific_subject_type():
    assert _coerce_subject_type_to_supported_main_type(
        {
            "subject_type": "EDC机能包",
            "workflow_template": "edc_tactical",
        }
    ) == ""


def test_build_profile_summary_falls_back_when_theme_only_repeats_identity():
    summary = _build_profile_summary(
        {
            "subject_brand": "REATE",
            "subject_model": "EXO-M",
            "subject_type": "EDC折刀",
            "workflow_template": "unboxing_standard",
            "video_theme": "REATE EXO-M 开箱评测",
        }
    )

    assert "内容方向偏产品开箱与上手体验" in summary
    assert "内容方向偏REATE EXO-M 开箱评测" not in summary


def test_build_profile_summary_prefers_ai_domain_fallback_over_tutorial_template_copy():
    summary = _build_profile_summary(
        {
            "workflow_template": "tutorial_standard",
            "content_kind": "tutorial",
            "subject_domain": "ai",
            "subject_brand": "ComfyUI",
            "subject_type": "AI工作流工具",
            "video_theme": "ComfyUI 教程",
        }
    )

    assert "内容方向偏AI工作流与模型能力讲解" in summary
    assert "内容方向偏软件流程演示与步骤讲解" not in summary


def test_build_profile_summary_prefers_tech_domain_fallback_over_tutorial_template_copy():
    summary = _build_profile_summary(
        {
            "workflow_template": "tutorial_standard",
            "content_kind": "tutorial",
            "subject_domain": "tech",
            "subject_brand": "iPhone",
            "subject_type": "手机",
            "video_theme": "iPhone 教程",
        }
    )

    assert "内容方向偏数码科技体验与功能讲解" in summary
    assert "内容方向偏软件流程演示与步骤讲解" not in summary


def test_build_profile_summary_uses_neutral_fallback_for_unknown_generic_subject():
    summary = _build_profile_summary(
        {
            "workflow_template": "",
            "content_kind": "",
            "subject_domain": "",
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "video_theme": "",
        }
    )

    assert "主题待进一步确认" in summary
    assert "开箱产品" not in summary
    assert "产品开箱与上手体验" not in summary


def test_build_profile_summary_keeps_specific_theme_when_identity_missing_but_theme_is_strong():
    summary = _build_profile_summary(
        {
            "workflow_template": "unboxing_standard",
            "content_kind": "unboxing",
            "subject_domain": "edc",
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "video_theme": "MT33开箱与上手评测",
        }
    )

    assert "MT33开箱与上手评测" in summary
    assert "主题待进一步确认" not in summary


def test_build_conservative_identity_summary_uses_neutral_subject_when_identity_missing():
    summary = _build_conservative_identity_summary(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "video_theme": "",
        },
        subtitle_items=[
            {
                "text_raw": "今天主要看数字人口播的表达自然不自然。",
                "text_final": "今天主要看数字人口播的表达自然不自然。",
            }
        ],
    )

    assert "开箱产品" not in summary
    assert "主体待进一步确认" in summary


def test_build_conservative_identity_summary_keeps_specific_theme_when_identity_is_weak():
    summary = _build_conservative_identity_summary(
        {
            "subject_brand": "",
            "subject_model": "MT33",
            "subject_type": "",
            "video_theme": "MT33开箱与上手评测",
        },
        subtitle_items=[
            {
                "text_raw": "这期主要看 MT33 的整体设计和细节。",
                "text_final": "这期主要看 MT33 的整体设计和细节。",
            }
        ],
    )

    assert "MT33开箱与上手评测" in summary
    assert "主体待进一步确认" not in summary


def test_fallback_profile_uses_ai_domain_specific_theme_when_transcript_points_to_ai():
    profile = _fallback_profile(
        source_name="workflow.mp4",
        workflow_template="tutorial_standard",
        transcript_excerpt="今天主要演示 ComfyUI 的节点编排、工作流和模型推理。",
    )

    assert profile["subject_domain"] == "ai"
    assert profile["video_theme"] == "AI工作流与模型能力讲解"


def test_fallback_profile_prefers_commentary_template_for_podcast_like_transcript():
    profile = _fallback_profile(
        source_name="avatar-podcast.mp4",
        workflow_template=None,
        transcript_excerpt="大家好欢迎来到我的播客测试现场，今天想聊聊数字人的表达是否自然，以及互动感够不够。",
    )

    assert profile["workflow_template"] == "commentary_focus"
    assert profile["content_kind"] == "commentary"
    assert profile["subject_type"] == "口播观点"
    assert profile["video_theme"] == "观点表达与信息拆解"


def test_build_transcript_excerpt_pulls_high_signal_items_from_later_segments():
    subtitle_items = [
        {"start_time": 0.0, "end_time": 1.0, "text_raw": "开场闲聊"},
        {"start_time": 2.0, "end_time": 3.0, "text_raw": "继续随便说两句"},
        {"start_time": 220.0, "end_time": 222.0, "text_raw": "ARC 这把工具真的很顺手"},
    ]

    excerpt = build_transcript_excerpt(subtitle_items, max_items=3, max_chars=200)

    assert "ARC" in excerpt


def test_seed_profile_from_subtitles_handles_edc_asr_aliases():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "来自慢的这个定位上来说是他家最高端的产品"},
            {"text_raw": "ARC 这把工具的单手开合很舒服"},
        ]
    )

    assert profile["subject_brand"] == "LEATHERMAN"
    assert profile["subject_model"] == "ARC"
    assert profile["subject_type_candidates"] == ["多功能工具钳"]


def test_seed_profile_from_subtitles_detects_reate_folding_knife_signals():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "这把锐特折刀的梯片手感不错"},
            {"text_raw": "柄身细节和锁片结构这次都做了调整"},
        ]
    )

    assert profile["subject_brand"] == "REATE"
    assert profile["subject_type_candidates"] == ["EDC折刀"]


def test_extract_reference_frames_falls_back_to_center_seek_when_thumbnail_filter_fails(tmp_path: Path, monkeypatch):
    outputs: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int):
            self.returncode = returncode

    monkeypatch.setattr("roughcut.review.content_profile._probe_duration", lambda path: 120.0)

    def fake_run(args, capture_output=True, timeout=0):
        outputs.append(list(args))
        out = Path(args[-1])
        if "thumbnail=90,scale=960:-2" in args:
            return Result(1)
        out.write_bytes(b"jpg")
        return Result(0)

    monkeypatch.setattr("subprocess.run", fake_run)

    frames = _extract_reference_frames(tmp_path / "demo.mp4", tmp_path, count=3)

    assert len(frames) == 3
    assert all(path.exists() for path in frames)
    assert any("thumbnail=90,scale=960:-2" in cmd for cmd in outputs)
    assert any("-update" in cmd for cmd in outputs)


def test_apply_visual_subject_guard_overrides_conflicting_subject_type():
    profile = {
        "subject_type": "智能灯具",
        "visual_hints": {
            "subject_type": "EDC折刀",
            "subject_brand": "REATE",
            "subject_model": "EXO-M",
            "visible_text": "MT33",
        },
    }

    _apply_visual_subject_guard(profile)

    assert profile["subject_type"] == "EDC折刀"
    assert profile["subject_brand"] == "REATE"
    assert profile["subject_model"] == "EXO-M"
    assert profile["visible_text"] == "MT33"


def test_apply_visual_subject_guard_prefers_explicit_visual_cluster():
    profile = {
        "subject_type": "智能灯具",
        "visual_hints": {
            "subject_type": "智能灯具",
            "subject_brand": "某台灯",
            "subject_model": "L1",
            "visible_text": "L1",
        },
        "visual_cluster_hints": {
            "subject_type": "EDC折刀",
            "subject_brand": "NOC",
            "subject_model": "MT33",
            "visible_text": "NOC MT33",
        },
    }

    _apply_visual_subject_guard(profile)

    assert profile["subject_type"] == "EDC折刀"
    assert profile["subject_brand"] == "NOC"
    assert profile["subject_model"] == "MT33"
    assert profile["visible_text"] == "NOC MT33"


@pytest.mark.asyncio
async def test_infer_visual_profile_hints_extracts_visible_identity(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    async def fake_complete_with_images(*args, **kwargs):
        return '{"subject_type":"EDC机能包","subject_brand":"FOXBAT狐蝠工业","subject_model":"F21小副包","visible_text":"FOXBAT F21","reason":"包装正面可见品牌和型号"}'

    monkeypatch.setattr(content_profile_module, "complete_with_images", fake_complete_with_images)

    hints = await _infer_visual_profile_hints([])
    assert hints == {}


@pytest.mark.asyncio
async def test_infer_visual_profile_hints_prompt_includes_bag_and_flashlight_categories(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    captured: dict[str, str] = {}

    async def fake_complete_with_images(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return '{"subject_type":"EDC机能包","subject_brand":"FOXBAT狐蝠工业","subject_model":"F21小副包","visible_text":"FOXBAT F21","reason":"包装正面可见品牌和型号"}'

    monkeypatch.setattr(content_profile_module, "complete_with_images", fake_complete_with_images)

    hints = await _infer_visual_profile_hints([Path("frame_01.jpg")])

    assert hints["subject_type"] == "EDC机能包"
    assert "EDC机能包" in captured["prompt"]
    assert "EDC手电" in captured["prompt"]


@pytest.mark.asyncio
async def test_enrich_content_profile_does_not_call_legacy_visual_subject_guard(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def fail_guard(*args, **kwargs):
        raise AssertionError("legacy visual subject guard should not be used")

    monkeypatch.setattr(content_profile_module, "_apply_visual_subject_guard", fail_guard)

    result = await enrich_content_profile(
        profile={
            "subject_type": "EDC手电",
            "visible_text": "狐蝠工业 FXX1小副包 开箱",
            "visual_cluster_hints": {
                "subject_type": "EDC机能包",
                "subject_brand": "狐蝠工业",
                "subject_model": "FXX1小副包",
                "visible_text": "狐蝠工业 FXX1小副包",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "video_theme": "狐蝠工业FXX1小副包开箱与挂点评测",
                }
            },
            "ocr_evidence": {
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
            },
            "summary": "围绕狐蝠工业 FXX1小副包展开。",
            "engagement_question": "你更看重挂点还是分仓？",
        },
        source_name="IMG_0041.MOV",
        workflow_template="edc_tactical",
        transcript_excerpt="这期主要看分仓、挂点和日常收纳。",
        include_research=False,
    )

    assert result["subject_type"] == "EDC手电"
    assert result["subject_brand"] == "狐蝠工业"
    assert result["subject_model"] == "FXX1小副包"


@pytest.mark.asyncio
async def test_infer_visual_profile_hints_votes_across_frames(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        frame_name = image_paths[0].name
        if frame_name == "frame_01.jpg":
            return '{"subject_type":"EDC机能包","subject_brand":"FOXBAT狐蝠工业","subject_model":"F21小副包","visible_text":"FOXBAT F21","reason":"包装正面清晰"}'
        if frame_name == "frame_02.jpg":
            return '{"subject_type":"EDC机能包","subject_brand":"FOXBAT狐蝠工业","subject_model":"F21小副包","visible_text":"F21","reason":"侧面型号可见"}'
        if frame_name == "frame_03.jpg":
            return '{"subject_type":"EDC机能包","subject_brand":"头狼工业","subject_model":"副包","visible_text":"WOLF","reason":"背景卡片误识别"}'
        return "{}"

    monkeypatch.setattr(content_profile_module, "complete_with_images", fake_complete_with_images)

    hints = await _infer_visual_profile_hints(
        [Path("frame_01.jpg"), Path("frame_02.jpg"), Path("frame_03.jpg")]
    )

    assert hints["subject_type"] == "EDC机能包"
    assert hints["subject_brand"] == "FOXBAT狐蝠工业"
    assert hints["subject_model"] == "F21小副包"
    assert hints["visible_text"] == "FOXBAT F21"


def test_aggregate_visual_profile_hints_prefers_visible_text_supported_by_identity_cluster():
    hints = _aggregate_visual_profile_hints(
        [
            {
                "subject_type": "EDC机能包",
                "subject_brand": "FOXBAT狐蝠工业",
                "subject_model": "F21小副包",
                "visible_text": "FOXBAT F21",
                "reason": "包装正面清晰",
            },
            {
                "subject_type": "EDC机能包",
                "subject_brand": "FOXBAT狐蝠工业",
                "subject_model": "F21小副包",
                "visible_text": "F21",
                "reason": "侧面型号可见",
            },
            {
                "subject_type": "EDC机能包",
                "visible_text": "WOLF",
                "reason": "背景卡片误识别",
            },
            {
                "subject_type": "EDC机能包",
                "visible_text": "WOLF",
                "reason": "桌面贴纸误识别",
            },
        ]
    )

    assert hints["subject_brand"] == "FOXBAT狐蝠工业"
    assert hints["subject_model"] == "F21小副包"
    assert hints["visible_text"] == "FOXBAT F21"


def test_aggregate_visual_profile_hints_prefers_coherent_identity_cluster_over_split_votes():
    hints = _aggregate_visual_profile_hints(
        [
            {
                "subject_type": "EDC折刀",
                "subject_brand": "NOC",
                "subject_model": "MT33",
                "visible_text": "NOC MT33",
                "reason": "包装正面清晰",
            },
            {
                "subject_type": "EDC折刀",
                "subject_brand": "NOC",
                "visible_text": "NOC",
                "reason": "品牌 logo 清晰",
            },
            {
                "subject_type": "EDC折刀",
                "subject_model": "ARC",
                "visible_text": "ARC",
                "reason": "背景工具钳卡片误识别",
            },
            {
                "subject_type": "EDC折刀",
                "subject_model": "ARC",
                "visible_text": "ARC",
                "reason": "桌面贴纸误识别",
            },
        ]
    )

    assert hints["subject_brand"] == "NOC"
    assert hints["subject_model"] == "MT33"
    assert hints["visible_text"] == "NOC MT33"


def test_filter_evidence_by_visual_subject_drops_conflicting_lighting_results():
    evidence = [
        {"query": "MT33 开箱", "title": "某某智能台灯评测", "snippet": "这款台灯的光线很舒服"},
        {"query": "MT33 折刀", "title": "MT33 折刀开箱", "snippet": "这把折刀的刀柄和锁片细节不错"},
    ]

    filtered = _filter_evidence_by_visual_subject(evidence, visual_subject_type="EDC折刀")

    assert len(filtered) == 1
    assert filtered[0]["title"] == "MT33 折刀开箱"


def test_seed_profile_from_subtitles_detects_runninghub_infinite_canvas_theme():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "今天 RunningHub 上线了一个全新的功能叫无限画布"},
            {"text_raw": "这个功能很适合拿来搭漫剧工作流和节点编排"},
        ]
    )

    assert profile["subject_brand"] == "RunningHub"
    assert profile["subject_model"] == "无限画布"
    assert profile["subject_type_candidates"] == ["AI工作流创作平台"]
    assert any("无限画布" in item for item in profile["video_theme_candidates"])
    assert any("RunningHub 无限画布" in item for item in profile["search_queries"])


def test_seed_profile_from_subtitles_prefers_runninghub_from_rh_alias_over_later_model_names():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "今天那个 RH 上线了一个全新的功能，叫无限画布。"},
            {"text_raw": "后面这个工作流里也能接 Gemini 和 OpenAI。"},
        ]
    )

    assert profile["subject_brand"] == "RunningHub"
    assert profile["subject_model"] == "无限画布"


def test_seed_profile_from_user_memory_only_returns_supported_hits():
    profile = _seed_profile_from_user_memory(
        "这次来聊 ARC 这把工具的单手开合和锁点机构",
        {
            "field_preferences": {
                "subject_brand": [{"value": "LEATHERMAN", "count": 3}],
                "subject_model": [{"value": "ARC", "count": 5}],
            },
            "keyword_preferences": [{"keyword": "LEATHERMAN ARC", "count": 4}],
        },
    )

    assert profile["subject_model"] == "ARC"
    assert "subject_brand" not in profile


def test_assess_content_profile_automation_blocks_product_profile_without_identity():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "unboxing_upgrade",
            "subject_type": "多功能工具钳",
            "video_theme": "升级结构与上手体验",
            "summary": "这条视频主要围绕多功能工具钳的升级结构和上手体验展开，重点看开合手感和锁定机构。",
            "engagement_question": "这次升级你最在意开合还是锁定机构？",
            "search_queries": ["工具钳 升级 开箱", "工具钳 锁定机构"],
            "cover_title": {"top": "工具钳", "main": "升级结构开箱", "bottom": "锁定机构细看"},
            "evidence": [{"title": "demo"}],
        },
        subtitle_items=[
            {"text_raw": "这次先看升级后的锁定机构"},
            {"text_raw": "后面再看实际开合手感"},
            {"text_raw": "整体结构变化比较明显"},
            {"text_raw": "握持和受力也有变化"},
            {"text_raw": "我会重点看耐用度"},
            {"text_raw": "最后聊聊值不值得升级"},
        ],
    )

    assert assessment["auto_confirm"] is False
    assert "开箱类视频未识别出可验证主体" in assessment["blocking_reasons"]


def test_assess_content_profile_automation_blocks_conflicting_brand_and_model():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "edc_tactical",
            "subject_brand": "LEATHERMAN",
            "subject_model": "SK05二代Pro UV版",
            "subject_type": "EDC手电",
            "video_theme": "手电开箱与对比评测",
            "summary": "这条视频重点讲 SK05二代Pro UV版 的升级和上手体验。",
            "engagement_question": "这次升级你最在意哪一项？",
            "search_queries": ["Loop露普 SK05二代Pro UV版", "SK05二代Pro UV版 开箱"],
            "cover_title": {"top": "Loop露普", "main": "SK05二代Pro UV版", "bottom": "开箱对比"},
            "evidence": [{"title": "Loop露普 SK05二代Pro UV版"}],
        },
        subtitle_items=[
            {"text_raw": "这次主要看 Loop露普 SK05二代Pro UV版 的二代变化和 UV 表现。"},
            {"text_raw": "后面再看泛光和实际使用。"},
            {"text_raw": "这代的灯珠排列也有变化。"},
        ],
    )

    assert assessment["auto_confirm"] is False
    assert "开箱类视频主体品牌与型号冲突" in assessment["blocking_reasons"]


def test_assess_content_profile_automation_blocks_first_seen_product_identity():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
            "summary": "这条视频主要围绕一款EDC机能包展开，重点看分仓、挂点、收纳，具体品牌型号待人工确认。",
            "engagement_question": "你更看重副包的分仓还是挂点？",
            "search_queries": ["狐蝠工业 FXX1小副包"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "transcript_excerpt": "[0.0-2.0] 这期鸿福 F叉二一小副包做个开箱测评。",
        },
        subtitle_items=[
            {"text_raw": "这期鸿福 F叉二一小副包做个开箱测评。"},
            {"text_raw": "重点看分仓和挂点设计。"},
            {"text_raw": "日常收纳会更直观一点。"},
        ],
        user_memory={},
        glossary_terms=[
            {"correct_form": "狐蝠工业", "wrong_forms": ["鸿福", "狐蝠"], "category": "bag_brand"},
            {"correct_form": "FXX1小副包", "wrong_forms": ["F叉二一小副包"], "category": "bag_model"},
        ],
        source_name="IMG_0025.mp4",
    )

    assert assessment["auto_confirm"] is False
    assert "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认" in assessment["blocking_reasons"]
    assert assessment["identity_review"]["required"] is True
    assert assessment["identity_review"]["conservative_summary"] is True
    evidence_bundle = assessment["identity_review"]["evidence_bundle"]
    assert evidence_bundle["candidate_brand"] == "狐蝠工业"
    assert evidence_bundle["candidate_model"] == "FXX1小副包"
    assert evidence_bundle["matched_glossary_aliases"]["brand"] == ["鸿福"]
    assert evidence_bundle["matched_glossary_aliases"]["model"] == ["F叉二一小副包"]
    assert evidence_bundle["matched_subtitle_snippets"]
    assert evidence_bundle["matched_subtitle_snippets"][0].endswith("这期鸿福 F叉二一小副包做个开箱测评。")


def test_assess_content_profile_automation_blocks_ingestible_product_mislabeled_as_gear():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "edc_tactical",
            "subject_type": "多功能工具钳",
            "video_theme": "高价工具钳开箱",
            "summary": "这条视频主要围绕多功能工具钳展开，重点看上手体验和开箱包装。",
            "engagement_question": "这类工具钳你会随身带吗？",
            "search_queries": ["工具钳 开箱", "工具钳 上手"],
            "cover_title": {"top": "多功能工具钳", "main": "高价工具钳开箱", "bottom": "这次升级到位吗"},
            "evidence": [{"title": "demo"}],
        },
        subtitle_items=[
            {"text_raw": "今天给大家介绍一个 LuckyKiss 的。"},
            {"text_raw": "益生菌含片这个产品它叫 KissPod。"},
            {"text_raw": "这个含片直接给它放进去。"},
            {"text_raw": "口气清新的能力还是相当不错。"},
            {"text_raw": "一个是三百亿的这个益生菌。"},
            {"text_raw": "另外它是这个零糖。"},
        ],
    )

    assert assessment["auto_confirm"] is False
    assert "字幕显示为含片/益生菌等入口产品，但当前摘要主体仍落在装备/工具类" in assessment["blocking_reasons"]


def test_assess_content_profile_automation_respects_content_understanding_needs_review():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "F21小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业F21小副包开箱与上手评测",
            "summary": "这条视频主要围绕狐蝠工业 F21小副包展开。",
            "engagement_question": "你更看重分仓还是挂点？",
            "search_queries": ["狐蝠工业 F21小副包"],
            "cover_title": {"top": "狐蝠工业", "main": "F21小副包", "bottom": "开箱上手"},
            "content_understanding": {
                "needs_review": True,
                "review_reasons": ["联网搜索与内部已确认实体存在冲突，需人工复核"],
            },
        },
        subtitle_items=[
            {"text_raw": "这次主要看狐蝠工业 F21 小副包的分仓和挂点。"},
            {"text_raw": "后面再看上手细节。"},
            {"text_raw": "最后聊聊收纳体验。"},
            {"text_raw": "这次主要看挂点布局。"},
            {"text_raw": "整体结构比上一代更紧凑。"},
            {"text_raw": "最后再看值不值得买。"},
        ],
        auto_confirm_enabled=True,
        threshold=0.1,
    )

    assert assessment["auto_confirm"] is False
    assert "联网搜索与内部已确认实体存在冲突，需人工复核" in assessment["blocking_reasons"]


def test_assess_content_profile_automation_keeps_llm_review_reasons_when_no_manual_block():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "tutorial_default",
            "subject_type": "AI工作流创作平台",
            "video_theme": "ComfyUI 无限画布工作流实操",
            "summary": "这条视频主要围绕 ComfyUI 无限画布工作流展开。",
            "engagement_question": "你现在最卡在哪一步？",
            "search_queries": ["ComfyUI 无限画布 工作流"],
            "cover_title": {"top": "ComfyUI", "main": "无限画布实操", "bottom": "工作流拆开讲"},
            "content_understanding": {
                "needs_review": False,
                "review_reasons": ["型号信息缺失，但不影响当前视频主题判断"],
            },
        },
        subtitle_items=[
            {"text_raw": "这期主要讲 ComfyUI 无限画布工作流。"},
            {"text_raw": "后面我会拆开节点配置。"},
            {"text_raw": "最后给你一套可复用思路。"},
            {"text_raw": "先看布局，再看节点串联。"},
            {"text_raw": "最后看调参顺序。"},
            {"text_raw": "这样更容易复现。"},
        ],
        auto_confirm_enabled=False,
    )

    assert "型号信息缺失，但不影响当前视频主题判断" in assessment["review_reasons"]
    assert "型号信息缺失，但不影响当前视频主题判断" not in assessment["blocking_reasons"]


def test_assess_content_profile_automation_identity_evidence_bundle_reads_graph_ocr_and_transcript_labels():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与挂点评测",
            "summary": "围绕狐蝠工业 FXX1小副包展开。",
            "engagement_question": "你更看重挂点还是分仓？",
            "search_queries": ["狐蝠工业 FXX1小副包"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "transcript_excerpt": "这期主要看分仓和挂点。",
            "ocr_evidence": {
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                }
            },
        },
        subtitle_items=[
            {"text_raw": "这期主要看分仓和挂点。"},
        ],
        user_memory={
            "confirmed_entities": [
                {
                    "brand": "狐蝠工业",
                    "model": "FXX1小副包",
                    "phrases": ["狐蝠工业FXX1小副包", "FXX1小副包"],
                    "subject_type": "EDC机能包",
                    "subject_domain": "edc",
                }
            ]
        },
        glossary_terms=[
            {"correct_form": "狐蝠工业", "wrong_forms": ["鸿福"], "category": "bag_brand"},
            {"correct_form": "FXX1小副包", "wrong_forms": ["F叉二一小副包"], "category": "bag_model"},
        ],
        source_name="IMG_0025.mp4",
    )

    evidence_bundle = assessment["identity_review"]["evidence_bundle"]

    assert evidence_bundle["graph_confirmed_entities"][0]["brand"] == "狐蝠工业"
    assert evidence_bundle["matched_ocr_terms"] == ["狐蝠工业", "FXX1小副包"]
    assert evidence_bundle["matched_transcript_source_labels"]["subject_brand"] == "狐蝠工业"
    assert evidence_bundle["matched_transcript_source_labels"]["subject_model"] == "FXX1小副包"


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_accepts_draft_without_reenrichment(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    async def fail_enrich(*args, **kwargs):
        raise AssertionError("empty confirm should not re-enrich draft")

    monkeypatch.setattr(content_profile_module, "enrich_content_profile", fail_enrich)

    draft = {
        "subject_brand": "RunningHub",
        "subject_model": "无限画布",
        "summary": "现有草稿摘要",
        "transcript_excerpt": "测试字幕",
    }
    result = await apply_content_profile_feedback(
        draft_profile=draft,
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={},
    )

    assert result["subject_brand"] == "RunningHub"
    assert result["summary"] == "现有草稿摘要"
    assert result["review_mode"] == "manual_confirmed"
    assert result["user_feedback"] == {}


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_keeps_specific_subject_type_on_empty_feedback(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    async def fail_enrich(*args, **kwargs):
        raise AssertionError("empty confirm should not re-enrich draft")

    monkeypatch.setattr(content_profile_module, "enrich_content_profile", fail_enrich)

    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_type": "EDC机能包",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "summary": "现有草稿摘要",
            "transcript_excerpt": "测试字幕",
        },
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={},
    )

    assert result["subject_type"] == "EDC机能包"
    assert result["subject_brand"] == "狐蝠工业"
    assert result["subject_model"] == "FXX1小副包"
    assert result["review_mode"] == "manual_confirmed"
    assert result["user_feedback"] == {}


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_prefers_user_values():
    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_brand": "FAS",
            "subject_model": "旧型号",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "transcript_excerpt": "测试字幕",
        },
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={
            "subject_brand": "REATE",
            "subject_model": "马年限定版",
            "subject_type": "EDC折刀",
            "hook_line": "REATE 这把雕刻折刀终于来了",
            "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
            "summary": "这是用户确认后的摘要",
            "keywords": ["REATE", "马年限定版", "EDC折刀"],
        },
    )

    assert result["subject_brand"] == "REATE"
    assert result["subject_model"] == "马年限定版"
    assert result["subject_type"] == "EDC折刀"
    assert result["summary"] == "这是用户确认后的摘要"
    assert result["engagement_question"] == "这把 REATE 折刀你最想先看雕刻细节还是开合手感？"
    assert result["search_queries"]
    assert any("REATE" in item for item in result["search_queries"])
    assert any(token in result["cover_title"]["main"] for token in ("REATE", "马年限定版"))
    assert result["review_mode"] == "manual_confirmed"


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_prefers_reviewed_subtitle_excerpt(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    captured: dict[str, str] = {}

    def raising_provider():
        raise RuntimeError("provider unavailable")

    async def fake_enrich_content_profile(*, profile, source_name, channel_profile, transcript_excerpt, include_research, user_memory=None):
        captured["transcript_excerpt"] = transcript_excerpt
        return {
            **profile,
            "summary": "交叉校对后的摘要",
            "search_queries": ["REATE EXO-M 开箱"],
            "cover_title": {"top": "REATE", "main": "EXO-M开箱", "bottom": "开合手感"},
        }

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "enrich_content_profile", fake_enrich_content_profile)

    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_brand": "锐特",
            "subject_model": "旧型号",
            "transcript_excerpt": "旧字幕摘录",
        },
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={
            "subject_brand": "REATE",
            "subject_model": "EXO-M",
        },
        reviewed_subtitle_excerpt="更正后的字幕提到 REATE EXO-M 和开合手感。",
        accepted_corrections=[
            {"original": "锐特", "accepted": "REATE"},
            {"original": "旧型号", "accepted": "EXO-M"},
        ],
    )

    assert captured["transcript_excerpt"] == "更正后的字幕提到 REATE EXO-M 和开合手感。"
    assert result["subject_brand"] == "REATE"
    assert result["subject_model"] == "EXO-M"
    assert result["review_mode"] == "manual_confirmed"


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_keeps_llm_derived_fields_from_resolved_patch(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "subject_brand": "傲雷",
                "subject_model": "司令官2Ultra",
                "subject_type": "傲雷司令官2手电筒",
                "video_theme": "傲雷司令官2Ultra版本选购与参数对比",
                "hook_line": "司令官2Ultra到底值不值",
                "summary": "围绕傲雷司令官2Ultra的版本差异和参数表现展开讨论。",
                "engagement_question": "你会选司令官2Ultra还是更便宜的版本？",
                "search_queries": ["傲雷 司令官2Ultra", "司令官2Ultra 参数对比"],
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    async def fake_enrich_content_profile(*, profile, source_name, channel_profile, transcript_excerpt, include_research, user_memory=None):
        return {
            **profile,
            "subject_type": "EDC手电",
            "video_theme": "手电筒版本选购对比",
            "hook_line": "花100块买ULTRA值不值？",
            "summary": "视频博主分享SLIM2代ULTRA版手电筒选购心得。",
            "search_queries": ["SLIM2手电筒ULTRA版"],
            "cover_title": {"top": "手电", "main": "版本对比", "bottom": "怎么买"},
        }

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())
    monkeypatch.setattr(content_profile_module, "enrich_content_profile", fake_enrich_content_profile)

    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_brand": "耐克",
            "subject_model": "SK05",
            "subject_type": "SLIM2代ULTRA版手电筒",
            "video_theme": "手电筒版本选购对比",
            "transcript_excerpt": "这次主要看 ultra 和 pro 版本的区别。",
            "workflow_template": "edc_tactical",
        },
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
    )

    assert result["subject_brand"] == "傲雷"
    assert result["subject_model"] == "司令官2Ultra"
    assert result["subject_type"] == "傲雷司令官2手电筒"
    assert result["video_theme"] == "傲雷司令官2Ultra版本选购与参数对比"
    assert result["hook_line"] == "司令官2Ultra到底值不值"
    assert result["summary"] == "围绕傲雷司令官2Ultra的版本差异和参数表现展开讨论。"
    assert result["engagement_question"] == "你会选司令官2Ultra还是更便宜的版本？"
    assert result["search_queries"] == ["傲雷 司令官2Ultra", "司令官2Ultra 参数对比"]
    assert "傲雷" in result["cover_title"]["top"] or "傲雷" in result["cover_title"]["main"]


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_preserves_workflow_mode_enhancement_modes_and_keywords(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    captured: dict[str, object] = {}

    async def fake_enrich_content_profile(*, profile, source_name, channel_profile, transcript_excerpt, include_research, user_memory=None):
        captured["profile"] = dict(profile)
        return {**profile, "transcript_excerpt": transcript_excerpt}

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "enrich_content_profile", fake_enrich_content_profile)

    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_brand": "DJI",
            "subject_model": "Mini 4 Pro",
            "subject_type": "无人机",
            "video_theme": "DJI Mini 4 Pro 开箱评测",
            "summary": "原始摘要",
            "workflow_mode": "review",
            "enhancement_modes": ["semantic_search", "subtitle_polish"],
            "keywords": ["DJI Mini 4 Pro", "开箱"],
            "transcript_excerpt": "这次先看 DJI Mini 4 Pro 的开箱和评测。",
        },
        source_name="demo.mp4",
        channel_profile=None,
        user_feedback={
            "summary": "确认后摘要",
        },
    )

    assert result["workflow_mode"] == "review"
    assert result["enhancement_modes"] == ["semantic_search", "subtitle_polish"]
    captured_profile = captured["profile"]
    assert captured_profile["workflow_mode"] == "review"
    assert captured_profile["enhancement_modes"] == ["semantic_search", "subtitle_polish"]
    assert captured_profile["keywords"][0].replace(" ", "").casefold() == "djimini4pro"
    assert "开箱" in captured_profile["keywords"]


@pytest.mark.asyncio
async def test_resolve_content_profile_review_feedback_returns_only_llm_resolved_patch(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "apply_feedback": True,
                "subject_brand": "傲雷",
                "subject_model": "",
                "subject_type": "傲雷司令官2手电筒",
                "search_queries": ["傲雷 司令官2 Ultra"],
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    result = await content_profile_module.resolve_content_profile_review_feedback(
        draft_profile={
            "subject_brand": "OLIGHT",
            "subject_model": "SLIM2 Ultra",
            "subject_type": "EDC手电",
        },
        source_name="video.mp4",
        review_feedback="品牌改成傲雷，型号改成司令官2Ultra。",
        proposed_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
        reviewed_subtitle_excerpt="这次主要看 slim2 ultra 和 pro 版本的区别。",
    )

    assert result["subject_brand"] == "傲雷"
    assert result["subject_type"] == "傲雷司令官2手电筒"
    assert "傲雷" in result["keywords"]
    assert any("司令官2" in item for item in result["keywords"])


@pytest.mark.asyncio
async def test_resolve_content_profile_review_feedback_retries_when_verification_strong_but_first_pass_rejects(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_verify import HybridVerificationBundle

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def as_json(self):
            return dict(self._payload)

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse({"apply_feedback": False, "reason": "当前草稿品牌与审核意见不一致"})
            return FakeResponse(
                {
                    "apply_feedback": True,
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2Ultra",
                }
            )

    provider = FakeProvider()
    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: provider)

    result = await content_profile_module.resolve_content_profile_review_feedback(
        draft_profile={
            "subject_brand": "耐克",
            "subject_model": "SK05",
            "subject_type": "SLIM2代ULTRA版手电筒",
        },
        source_name="video.mp4",
        review_feedback="品牌改成傲雷，型号改成司令官2Ultra。",
        proposed_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
        verification_bundle=HybridVerificationBundle(
            search_queries=["傲雷 司令官2Ultra"],
            online_results=[
                {
                    "title": "OLIGHT傲雷 司令官2 Ultra手电",
                    "snippet": "旗舰新品 司令官2 Ultra",
                }
            ],
            database_results=[
                {
                    "brand": "傲雷",
                    "model": "司令官2 Ultra",
                    "primary_subject": "EDC手电",
                }
            ],
        ),
    )

    assert provider.calls == 2
    assert result == {
        "subject_brand": "傲雷",
        "subject_model": "司令官2Ultra",
    }


@pytest.mark.asyncio
async def test_resolve_content_profile_review_feedback_repairs_truncated_json_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def __init__(self, content: str, payload: dict[str, Any] | None = None):
            self.content = content
            self._payload = payload

        def as_json(self):
            if self._payload is not None:
                return dict(self._payload)
            raise json.JSONDecodeError("bad json", self.content, 0)

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse('{"apply_feedback": true, "subject_brand": "傲雷"')
            return FakeResponse(
                '{"apply_feedback": true, "subject_brand": "傲雷", "subject_model": "司令官2Ultra"}',
                {
                    "apply_feedback": True,
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2Ultra",
                },
            )

    provider = FakeProvider()
    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: provider)

    result = await content_profile_module.resolve_content_profile_review_feedback(
        draft_profile={
            "subject_brand": "耐克",
            "subject_model": "SK05",
            "subject_type": "SLIM2代ULTRA版手电筒",
        },
        source_name="video.mp4",
        review_feedback="品牌改成傲雷，型号改成司令官2Ultra。",
        proposed_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
    )

    assert provider.calls == 2
    assert result == {
        "subject_brand": "傲雷",
        "subject_model": "司令官2Ultra",
    }


@pytest.mark.asyncio
async def test_resolve_content_profile_review_feedback_uses_minimal_patch_retry_when_strong_signal_still_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_verify import HybridVerificationBundle

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def as_json(self):
            return dict(self._payload)

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls < 3:
                return FakeResponse({"apply_feedback": False})
            return FakeResponse(
                {
                    "apply_feedback": True,
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2Ultra",
                }
            )

    provider = FakeProvider()
    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: provider)

    result = await content_profile_module.resolve_content_profile_review_feedback(
        draft_profile={
            "subject_brand": "耐克",
            "subject_model": "SK05",
            "subject_type": "SLIM2代ULTRA版手电筒",
        },
        source_name="video.mp4",
        review_feedback="品牌改成傲雷，型号改成司令官2Ultra。",
        proposed_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
        verification_bundle=HybridVerificationBundle(
            search_queries=["傲雷 司令官2Ultra"],
            online_results=[
                {
                    "title": "OLIGHT傲雷 司令官2 Ultra手电",
                    "snippet": "旗舰新品 司令官2 Ultra",
                },
                {
                    "title": "地表最硬便携手电筒?傲雷司令官Ultra多功能EDC手电测评",
                    "snippet": "傲雷司令官 Ultra 体验",
                },
            ],
            database_results=[
                {
                    "brand": "傲雷",
                    "model": "司令官2 Ultra",
                    "primary_subject": "EDC手电",
                }
            ],
        ),
    )

    assert provider.calls == 3
    assert result == {
        "subject_brand": "傲雷",
        "subject_model": "司令官2Ultra",
    }


def test_build_review_feedback_search_queries_expands_brand_model_and_subject_context():
    queries = build_review_feedback_search_queries(
        draft_profile={
            "subject_type": "EDC手电",
            "search_queries": ["SLIM2 Ultra 手电"],
        },
        proposed_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
    )

    assert "傲雷 司令官2Ultra" in queries
    assert "傲雷 司令官2Ultra EDC手电" in queries
    assert "司令官2Ultra EDC手电" in queries


def test_build_review_feedback_verification_snapshot_strips_blank_fragments():
    from roughcut.review.content_profile import _build_review_feedback_verification_snapshot

    snapshot = _build_review_feedback_verification_snapshot(
        SimpleNamespace(
            search_queries=[" 傲雷 司令官2 Ultra ", "  "],
            online_results=[
                {
                    "query": "  傲雷 司令官2 Ultra  ",
                    "title": " 旗舰新品 ",
                    "snippet": " 司令官2 Ultra 旗舰新品 ",
                    "url": " https://example.test/item ",
                },
                {
                    "query": "",
                    "title": "",
                    "snippet": "",
                    "url": "",
                },
            ],
            database_results=[
                {
                    "brand": " 傲雷 ",
                    "model": " 司令官2 Ultra ",
                    "primary_subject": " 司令官2 Ultra 手电 ",
                    "subject_type": " EDC手电 ",
                    "source_type": " 电商详情页 ",
                },
                {
                    "brand": " ",
                    "model": " ",
                    "primary_subject": "",
                    "subject_type": "",
                    "source_type": "",
                },
            ],
        )
    )

    assert snapshot["search_queries"] == ["傲雷 司令官2 Ultra"]
    assert snapshot["online_results"] == [
        {
            "query": "傲雷 司令官2 Ultra",
            "title": "旗舰新品",
            "snippet": "司令官2 Ultra 旗舰新品",
            "url": "https://example.test/item",
        }
    ]
    assert snapshot["database_results"] == [
        {
            "brand": "傲雷",
            "model": "司令官2 Ultra",
            "primary_subject": "司令官2 Ultra 手电",
            "subject_type": "EDC手电",
            "source_type": "电商详情页",
        }
    ]


@pytest.mark.asyncio
async def test_enrich_content_profile_uses_llm_to_replace_generic_engagement_question(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {"engagement_question": "ARC这次升级你最在意单手开合还是钳头？"}

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "升级开箱与上手体验",
            "engagement_question": "你觉得这次到手值不值？",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的单手开合和钳头结构。",
        include_research=False,
    )

    assert result["engagement_question"] == "ARC这次升级你最在意单手开合还是钳头？"


@pytest.mark.asyncio
async def test_infer_content_profile_uses_neutral_review_fallback_when_content_understanding_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from roughcut.review import content_profile as content_profile_module

    async def raising_infer_content_understanding(evidence_bundle):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(content_profile_module, "infer_content_understanding", raising_infer_content_understanding)
    monkeypatch.setattr(content_profile_module, "_extract_reference_frames", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        content_profile_module,
        "get_settings",
        lambda: SimpleNamespace(ocr_enabled=False),
    )

    result = await infer_content_profile(
        source_path=tmp_path / "bag.mp4",
        source_name="bag.mp4",
        subtitle_items=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 2.0,
                "text_raw": "这期聊一个机能双肩包，重点看分仓和背负。",
                "text_norm": "这期聊一个机能双肩包，重点看分仓和背负。",
                "text_final": "这期聊一个机能双肩包，重点看分仓和背负。",
            }
        ],
        workflow_template="edc_tactical",
        include_research=False,
    )

    assert result["subject_type"] == ""
    assert result["video_theme"] == ""
    assert result["summary"] == "这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。"
    assert result["content_understanding"]["needs_review"] is True
    assert "内容理解推断失败" in result["content_understanding"]["review_reasons"]
    assert result["cover_title"]["main"] == "内容待确认"


@pytest.mark.asyncio
async def test_enrich_content_profile_uses_content_understanding_inference(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity

    captured: dict[str, object] = {}

    async def fake_infer_content_understanding(evidence_bundle):
        captured["evidence_bundle"] = evidence_bundle
        return ContentUnderstanding(
            video_type="unboxing",
            content_domain="gear",
            primary_subject="EDC机能包",
            subject_entities=[
                SubjectEntity(
                    kind="product",
                    name="FOXBAT狐蝠工业 F21小副包",
                    brand="FOXBAT狐蝠工业",
                    model="F21小副包",
                )
            ],
            video_theme="FOXBAT狐蝠工业F21小副包开箱与分仓挂点评测",
            summary="这条视频主要围绕 FOXBAT狐蝠工业 F21小副包 的分仓和挂点展开。",
            hook_line="分仓挂点直接看",
            engagement_question="你更在意分仓还是挂点？",
            search_queries=["FOXBAT F21 小副包"],
            evidence_spans=[{"source": "ocr", "text": "FOXBAT F21"}],
            uncertainties=[],
            confidence={"overall": 0.91},
            needs_review=False,
            review_reasons=[],
        )

    monkeypatch.setattr(content_profile_module, "infer_content_understanding", fake_infer_content_understanding)

    result = await enrich_content_profile(
        profile={
            "subject_type": "开箱产品",
            "video_theme": "产品开箱与上手体验",
            "summary": "围绕开箱产品展开。",
            "ocr_evidence": {
                "visible_text": "FOXBAT F21 小副包 开箱",
            },
            "visual_cluster_hints": {
                "subject_brand": "FOXBAT狐蝠工业",
                "subject_model": "F21小副包",
                "visible_text": "FOXBAT F21",
            },
        },
        source_name="f21.mp4",
        workflow_template="edc_tactical",
        transcript_excerpt="今天开箱 FOXBAT 狐蝠工业 F21 小副包，重点看分仓和挂点。",
        include_research=False,
    )

    evidence_bundle = captured["evidence_bundle"]
    assert evidence_bundle["candidate_hints"]["subject_type"] == "开箱产品"
    assert evidence_bundle["candidate_hints"]["video_theme"] == "产品开箱与上手体验"
    assert result["subject_model"] == "F21小副包"
    assert result["subject_type"] == "EDC机能包"
    assert result["video_theme"] == "FOXBAT狐蝠工业F21小副包开箱与分仓挂点评测"
    assert result["summary"] == "这条视频主要围绕 FOXBAT狐蝠工业 F21小副包 的分仓和挂点展开。"
    assert result["content_understanding"]["primary_subject"] == "EDC机能包"


@pytest.mark.asyncio
async def test_enrich_content_profile_keeps_confirmed_fields_over_content_understanding(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module
    from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity

    async def fake_infer_content_understanding(evidence_bundle):
        return ContentUnderstanding(
            video_type="unboxing",
            content_domain="gear",
            primary_subject="EDC机能包",
            subject_entities=[
                SubjectEntity(
                    kind="product",
                    name="FOXBAT狐蝠工业 F21小副包",
                    brand="FOXBAT狐蝠工业",
                    model="F21小副包",
                )
            ],
            video_theme="FOXBAT狐蝠工业F21小副包开箱与分仓挂点评测",
            summary="这条视频主要围绕 FOXBAT狐蝠工业 F21小副包 的分仓和挂点展开。",
            hook_line="分仓挂点直接看",
            engagement_question="你更在意分仓还是挂点？",
            search_queries=["FOXBAT F21 小副包"],
            evidence_spans=[],
            uncertainties=[],
            confidence={"overall": 0.91},
            needs_review=False,
            review_reasons=[],
        )

    monkeypatch.setattr(content_profile_module, "infer_content_understanding", fake_infer_content_understanding)

    result = await enrich_content_profile(
        profile={
            "subject_type": "开箱产品",
            "video_theme": "产品开箱与上手体验",
            "user_feedback": {
                "subject_type": "人工确认主题",
                "video_theme": "人工确认的视频主题",
            },
        },
        source_name="f21.mp4",
        workflow_template="edc_tactical",
        transcript_excerpt="今天开箱 FOXBAT 狐蝠工业 F21 小副包，重点看分仓和挂点。",
        include_research=False,
    )

    assert result["subject_type"] == "人工确认主题"
    assert result["video_theme"] == "人工确认的视频主题"


@pytest.mark.asyncio
async def test_enrich_content_profile_clears_conflicting_theme_and_summary_from_resolved_current_entities(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC机能包",
            "video_theme": "ComfyUI 无限画布工作流实操",
            "summary": "主要讲 ComfyUI 工作流和节点编排。",
            "ocr_evidence": {
                "visible_text": "狐蝠工业 FXX1小副包 开箱",
            },
            "transcript_evidence": {
                "source_labels": {
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "video_theme": "狐蝠工业FXX1小副包开箱与挂点评测",
                }
            },
        },
        source_name="demo.mp4",
        channel_profile="edc_tactical",
        transcript_excerpt="这期主要看分仓、挂点和日常收纳。",
        include_research=False,
    )

    assert result["subject_brand"] == "狐蝠工业"
    assert result["subject_model"] == "FXX1小副包"
    assert result["video_theme"] == ""
    assert "狐蝠工业 FXX1小副包" in result["summary"]
    assert "ComfyUI" not in result["summary"]


@pytest.mark.asyncio
async def test_enrich_content_profile_backfills_identity_from_glossary_seed(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={},
        source_name="IMG_0001.mp4",
        channel_profile="edc_tactical",
        transcript_excerpt="今天开箱狐蝠工业 F21 小副包，先看一下这个分仓设计。",
        glossary_terms=[
            {
                "correct_form": "FOXBAT狐蝠工业",
                "wrong_forms": ["狐蝠工业", "FOXBAT"],
                "category": "bag_brand",
            }
        ],
        include_research=False,
    )

    assert result["subject_brand"] == "FOXBAT狐蝠工业"
    assert result["subject_model"] == "F21小副包"
    assert result.get("subject_type", "") == ""


@pytest.mark.asyncio
async def test_enrich_content_profile_does_not_classify_subject_type_from_context_seed(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={},
        source_name="IMG_0001.mp4",
        channel_profile="edc_tactical",
        transcript_excerpt="今天开箱狐蝠工业 F21 小副包，先看一下这个分仓设计。",
        glossary_terms=[
            {
                "correct_form": "FOXBAT狐蝠工业",
                "wrong_forms": ["狐蝠工业", "FOXBAT"],
                "category": "bag_brand",
            }
        ],
        include_research=False,
    )

    assert result["subject_brand"] == "FOXBAT狐蝠工业"
    assert result["subject_model"] == "F21小副包"
    assert result.get("subject_type", "") == ""


@pytest.mark.asyncio
async def test_enrich_content_profile_does_not_upgrade_generic_theme_from_context_seed(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_type": "开箱产品",
            "video_theme": "产品开箱与上手体验",
        },
        source_name="bag.mp4",
        channel_profile="edc_tactical",
        transcript_excerpt="今天开箱狐蝠工业 F21 小副包，重点看分仓、挂点和日常收纳。",
        glossary_terms=[
            {
                "correct_form": "FOXBAT狐蝠工业",
                "wrong_forms": ["狐蝠工业", "FOXBAT"],
                "category": "bag_brand",
            }
        ],
        include_research=False,
    )

    assert result["subject_brand"] == "FOXBAT狐蝠工业"
    assert result["subject_model"] == "F21小副包"
    assert result["subject_type"] == "开箱产品"
    assert result["video_theme"] == "产品开箱与上手体验"


@pytest.mark.asyncio
async def test_enrich_content_profile_falls_back_to_contextual_question_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "升级开箱与上手体验",
            "engagement_question": "你觉得这次到手值不值？",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的单手开合和钳头结构。",
        include_research=False,
    )

    assert result["engagement_question"] == "LEATHERMANARC这次升级你更在意开合还是钳头？"


@pytest.mark.asyncio
async def test_enrich_content_profile_prefers_focus_driven_question_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "产品开箱与上手体验",
            "engagement_question": "你觉得这次到手值不值？",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的锁定机构和开合手感，后面再看钳头结构。",
        include_research=False,
    )

    assert result["engagement_question"] == "LEATHERMANARC你更想先看锁定机构还是开合？"


@pytest.mark.asyncio
async def test_enrich_content_profile_backfills_focus_driven_hook_line(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "产品开箱与上手体验",
            "hook_line": "",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的锁定机构和开合手感，后面再看钳头结构。",
        include_research=False,
    )

    assert result["hook_line"] == "锁定机构直接看"


@pytest.mark.asyncio
async def test_enrich_content_profile_clears_unverified_brand_model(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN 莱泽曼",
            "subject_model": "ARC",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "visible_text": "LEATHERMAN ARC",
            "summary": "这次莱泽曼 ARC 的开箱主要看整体结构。",
            "engagement_question": "这把莱泽曼 ARC 值不值入手？",
            "search_queries": ["LEATHERMAN ARC", "LEATHERMAN ARC 开箱"],
            "cover_title": {
                "top": "莱泽曼ARC",
                "main": "旗舰工具钳开箱",
                "bottom": "360°彩合金结构+双咔哒开合",
            },
        },
        source_name="20260211-120947.mp4",
        channel_profile=None,
        transcript_excerpt="这次先看彩钛结构和组装细节，后面再看开合手感。",
        include_research=False,
    )

    assert result["subject_brand"] == ""
    assert result["subject_model"] == ""
    assert result["visible_text"] == ""
    assert not result["search_queries"]
    assert "ARC" not in result["cover_title"]["top"]
    assert "莱泽曼" not in result["summary"]
    assert "ARC" not in result["engagement_question"]


@pytest.mark.asyncio
async def test_enrich_content_profile_preserves_confirmed_user_feedback(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "visible_text": "LEATHERMAN ARC",
            "summary": "这期是 REATE 折刀雕刻开箱，不是工具钳节目。",
            "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
            "user_feedback": {
                "subject_brand": "REATE",
                "subject_type": "EDC折刀",
                "video_theme": "折刀雕刻开箱",
                "summary": "这期是 REATE 折刀雕刻开箱，不是工具钳节目。",
                "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
                "hook_line": "REATE 这把雕刻折刀终于来了",
                "keywords": ["REATE", "折刀", "开箱"],
            },
        },
        source_name="20260211-120947.mp4",
        channel_profile=None,
        transcript_excerpt="这次先看柄身雕刻和组装细节，后面再看开合手感。",
        include_research=False,
    )

    assert result["subject_brand"] == "REATE"
    assert result["subject_type"] == "EDC折刀"
    assert result["video_theme"] == "折刀雕刻开箱"
    assert result["summary"] == "这期是 REATE 折刀雕刻开箱，不是工具钳节目。"
    assert result["engagement_question"] == "这把 REATE 折刀你最想先看雕刻细节还是开合手感？"
    assert any("REATE" in item for item in result["search_queries"])
    assert result["cover_title"]["top"] == "REATE"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_uses_review_memory(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="来自慢这把多功能工具前的主到和单手开和都不错",
        text_norm="来自慢这把多功能工具前的主到和单手开和都不错",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [
                {"term": "LEATHERMAN"},
                {"term": "多功能工具钳"},
                {"term": "主刀"},
                {"term": "单手开合"},
            ],
            "aliases": [{"wrong": "来自慢", "correct": "LEATHERMAN"}],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert "LEATHERMAN" in item.text_final
    assert "多功能工具钳" in item.text_final
    assert "主刀" in item.text_final
    assert "单手开合" in item.text_final
    assert "来自慢" not in item.text_final
    assert "主到" not in item.text_final


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_uses_phrase_preferences(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这个次定配静面看起来会更亮一点",
        text_norm="这个次定配静面看起来会更亮一点",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "次顶配"}, {"term": "镜面"}],
            "aliases": [],
            "style_examples": [],
            "phrase_preferences": [{"phrase": "次顶配镜面", "count": 5}],
        },
    )

    assert polished == 1
    assert item.text_final == "次顶配镜面看起来会更亮一点"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_rewrites_sentence_slot_with_learned_phrase(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="首先,还是这个自定配顶面吧。",
        text_norm="首先,还是这个自定配顶面吧。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "次顶配"}, {"term": "镜面"}, {"term": "次顶配镜面"}],
            "aliases": [],
            "style_examples": [],
            "phrase_preferences": [{"phrase": "次顶配镜面", "count": 5}],
        },
    )

    assert polished == 1
    assert item.text_final == "首先,还是这个次顶配镜面吧。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_repairs_collapsed_predicate_clause(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="光线会更加精归。",
        text_norm="光线会更加精归。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "光线"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert item.text_final == "光线会更好。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_rejects_cross_episode_rewrite(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "items": [
                    {"index": 0, "text_final": "LEATHERMAN ARC深雕版，360度无死角钛合金雕刻"}
                ]
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这把 Reate 折刀先看手柄雕刻细节",
        text_norm="这把 Reate 折刀先看手柄雕刻细节",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={
            "preset_name": "edc_tactical",
            "subject_brand": "REATE",
            "subject_model": "",
            "subject_type": "EDC折刀",
        },
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "REATE"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert item.text_final == "这把 REATE 折刀先看手柄雕刻细节"
    assert "LEATHERMAN" not in item.text_final
    assert "ARC" not in item.text_final


@pytest.mark.asyncio
async def test_polish_subtitle_items_llm_result_still_runs_cleanup_pipeline(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "items": [
                    {"index": 0, "text_final": "光线会更加精归。"}
                ]
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="光线会更加精归。",
        text_norm="光线会更加精归。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "光线"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert item.text_final == "光线会更好。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_llm_prompt_includes_display_number_guidance(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "items": [
                    {"index": 0, "text_final": "这次拿到一个新的手电筒。"}
                ]
            }

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            prompt = messages[1].content
            assert "阿拉伯数字" in prompt
            assert "中文数字" in prompt
            assert "字母+数字" in prompt
            assert "日期时间" in prompt
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这次拿到1个新的手电筒。",
        text_norm="这次拿到1个新的手电筒。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical", "subject_type": "EDC手电"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "这次拿到一个新的手电筒。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_removes_leading_filler_words(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = True

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="呃然后这个包装小了一圈。",
        text_norm="呃然后这个包装小了一圈。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "包装小了一圈。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_applies_readable_number_strategy(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = False

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这个包装有两个档位，三月五号上午八点二十上线，a四纸也能放。",
        text_norm="这个包装有两个档位，三月五号上午八点二十上线，a四纸也能放。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "这个包装有2个档位， 3月5号上午8点20上线， A4纸也能放。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_can_disable_filler_cleanup(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = False

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="呃然后这个包装小了一圈。",
        text_norm="呃然后这个包装小了一圈。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "呃然后这个包装小了一圈。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_removes_trailing_filler_words(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = True

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这个尾绳孔做得非常好啊。",
        text_norm="这个尾绳孔做得非常好啊。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "尾绳孔做得非常好啊。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_removes_non_ah_ba_sentence_particle(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = True

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="尾按呢。",
        text_norm="尾按呢。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "尾按。"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_keeps_sentence_final_ba_and_adds_spacing(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    class DummySettings:
        subtitle_filler_cleanup_enabled = True

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)
    monkeypatch.setattr(content_profile_module, "get_settings", lambda: DummySettings())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="呃然后这个方案是第二代因为有两个档位吧。",
        text_norm="呃然后这个方案是第二代因为有两个档位吧。",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={"terms": [], "aliases": [], "style_examples": []},
    )

    assert polished == 1
    assert item.text_final == "方案是第2代 因为有2个档位吧。"
