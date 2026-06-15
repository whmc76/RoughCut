from roughcut.review.content_profile import (
    _backfill_subject_type_from_identity_review_entities,
    _build_profile_summary,
    _build_subtitle_signal_blob,
    _collect_identity_subtitle_snippets,
    apply_source_identity_constraints,
    build_transcript_excerpt,
    extract_source_identity_constraints,
)


SOURCE_NAME = "IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV"


def test_extracts_boltboat_eclipse_identity_from_source_name() -> None:
    constraints = extract_source_identity_constraints({}, source_name=SOURCE_NAME)

    assert constraints["authoritative"] is True
    assert constraints["subject_brand"] == "BOLTBOAT"
    assert constraints["subject_model"] == "影蚀"
    assert "机能" in constraints["subject_type"]


def test_source_identity_uses_primary_subject_before_comparison_target() -> None:
    constraints = extract_source_identity_constraints(
        {},
        source_name="IMG_0041 hsjun和boltboat联名 户外机能双肩包 游刃，黑白两个颜色的开箱评测，以及对比狐蝠工业阵风.MOV",
    )

    assert constraints["subject_brand"] == "BOLTBOAT"
    assert constraints["subject_model"] == "游刃"
    assert constraints["subject_type"] == "EDC机能包"
    assert "狐蝠工业" not in constraints["subject_brand"]
    assert "阵风" not in constraints["subject_model"]


def test_extracts_nitecore_edc17_flashlight_identity_from_source_name() -> None:
    constraints = extract_source_identity_constraints(
        {},
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
    )

    assert constraints["subject_brand"] == "NITECORE"
    assert constraints["subject_model"] == "EDC17"
    assert constraints["subject_type"] == "EDC手电"


def test_extracts_olight_chinese_filename_model_from_source_name() -> None:
    constraints = extract_source_identity_constraints(
        {},
        source_name="merged_3_傲雷掠夺者2mini战术手电开箱.mp4",
    )

    assert constraints["authoritative"] is True
    assert constraints["subject_brand"] == "OLIGHT"
    assert constraints["subject_model"] == "掠夺者2mini"
    assert constraints["subject_type"] == "EDC手电"


def test_extracts_olight_model_from_video_description() -> None:
    constraints = extract_source_identity_constraints(
        {
            "source_context": {
                "video_description": "这条视频主要开箱傲雷掠夺者2mini战术手电，重点看包装和上手体验。"
            }
        },
        source_name="merged_3.mp4",
    )

    assert constraints["authoritative"] is True
    assert constraints["subject_brand"] == "OLIGHT"
    assert constraints["subject_model"] == "掠夺者2mini"
    assert constraints["subject_type"] == "EDC手电"


def test_source_identity_overrides_transcript_side_model_contamination() -> None:
    profile = {
        "subject_brand": "OLIGHT",
        "subject_model": "SK05二代",
        "subject_type": "EDC手电",
        "summary": "这条视频主要围绕OLIGHT SK05二代展开，内容方向偏泛光展示。",
        "video_theme": "OLIGHT SK05二代泛光展示",
        "cover_title": {"top": "OLIGHT", "main": "SK05二代", "bottom": "SK05二代强光测试"},
    }

    constrained = apply_source_identity_constraints(
        profile,
        source_name="merged_3_傲雷掠夺者2mini战术手电开箱.mp4",
        transcript_excerpt="SK05的操作逻辑要简单得多，但今天开箱这个傲雷手电。",
    )

    assert constrained["subject_brand"] == "OLIGHT"
    assert constrained["subject_model"] == "掠夺者2mini"
    assert "SK05" not in constrained["video_theme"]
    assert "SK05" not in constrained["summary"]
    assert "SK05" not in "".join(str(value) for value in constrained["cover_title"].values())


def test_source_identity_overrides_related_profile_model_contamination() -> None:
    profile = {
        "subject_brand": "BOLTBOAT",
        "subject_model": "FXX1小副包",
        "subject_type": "EDC机能包",
        "summary": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "video_theme": "BOLTBOAT FXX1小副包挂点与收纳展示",
    }

    constrained = apply_source_identity_constraints(profile, source_name=SOURCE_NAME)

    assert constrained["subject_brand"] == "BOLTBOAT"
    assert constrained["subject_model"] == "影蚀"
    assert "FXX1" not in constrained["summary"]
    assert "FXX1" not in constrained["video_theme"]


def test_source_identity_rewrites_conflicting_edc_visible_text() -> None:
    profile = {
        "subject_model": "EDC17",
        "subject_type": "",
        "visible_text": "EDC37",
        "cover_title": {"top": "EDC37", "main": "EDC17", "bottom": "EDC17强光测试"},
        "summary": "EDC37 对比展示",
        "video_theme": "EDC37 对比",
    }

    constrained = apply_source_identity_constraints(
        profile,
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        transcript_excerpt="这个EDC17手电有UV和白光模式",
    )

    assert constrained["subject_brand"] == "NITECORE"
    assert constrained["subject_model"] == "EDC17"
    assert constrained["subject_type"] == "EDC手电"
    assert "EDC37" not in constrained["visible_text"]


def test_content_profile_semantic_excerpt_and_snippets_use_canonical_surface() -> None:
    subtitle_items = [
        {
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "那个 EDC 折刀",
            "text_norm": "这是 MAXACE 美杜莎4",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        {
            "start_time": 1.0,
            "end_time": 2.0,
            "text_raw": "看一下细节",
            "text_norm": "看一下细节",
            "text_final": "看一下细节",
        },
    ]

    excerpt = build_transcript_excerpt(subtitle_items)
    subtitle_blob = _build_subtitle_signal_blob(subtitle_items)
    snippets = _collect_identity_subtitle_snippets(
        "MAXACE",
        "美杜莎4",
        subtitle_items=subtitle_items,
        glossary_terms=[],
    )

    assert "这是 MAXACE 美杜莎4" in excerpt
    assert "EDC 折刀" not in subtitle_blob
    assert snippets == ["[0.0-1.0] 这是 MAXACE 美杜莎4"]


def test_build_profile_summary_avoids_generic_packaging_phrase_for_specific_product() -> None:
    profile = {
        "subject_brand": "NOC",
        "subject_model": "MT34",
        "subject_type": "EDC折刀",
        "subject_domain": "EDC刀具",
        "content_kind": "unboxing",
        "video_theme": "产品开箱与上手体验",
        "transcript_excerpt": "这次重点看锆合金版本、快开手感和背夹设计。",
    }

    summary = _build_profile_summary(profile)

    assert "适合后续做搜索校验、字幕纠错和剪辑包装" not in summary
    assert "适合后续做信息核对、字幕复核和图文包装" in summary
    assert "NOC MT34" in summary


def test_build_profile_summary_uses_detail_phrase_when_available() -> None:
    profile = {
        "subject_brand": "NOC",
        "subject_model": "MT34",
        "subject_type": "EDC折刀",
        "subject_domain": "EDC刀具",
        "content_kind": "unboxing",
        "video_theme": "产品开箱与上手体验",
        "content_understanding": {
            "semantic_facts": {
                "aspect_candidates": ["锆合金版本", "快开手感", "背夹设计"],
            }
        },
    }

    summary = _build_profile_summary(profile)

    assert "重点提到" in summary


def test_backfill_subject_type_from_graph_confirmed_entity_when_brand_model_match() -> None:
    patched = _backfill_subject_type_from_identity_review_entities(
        {
            "subject_brand": "NOC",
            "subject_model": "MT34",
            "subject_type": "",
            "subject_domain": "",
        },
        identity_review={
            "evidence_bundle": {
                "graph_confirmed_entities": [
                    {
                        "brand": "NOC",
                        "model": "MT34 / S06mini",
                        "subject_type": "EDC折刀",
                        "subject_domain": "edc",
                    },
                    {
                        "brand": "未知品牌",
                        "model": "别的型号",
                        "subject_type": "EDC手电",
                        "subject_domain": "edc",
                    },
                ]
            }
        },
    )

    assert patched["subject_type"] == "EDC折刀"
    assert patched["subject_domain"] == "edc"
