from __future__ import annotations

from roughcut.review.domain_glossaries import detect_glossary_domains, normalize_subject_domain
from roughcut.review.subtitle_memory import (
    apply_domain_term_corrections,
    build_subtitle_review_memory,
    build_transcription_prompt,
    summarize_subtitle_review_memory,
)


def test_build_subtitle_review_memory_collects_terms_and_examples():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[
            {
                "correct_form": "LEATHERMAN",
                "wrong_forms": ["来泽曼", "来自慢"],
                "category": "brand",
            }
        ],
        user_memory={
            "field_preferences": {
                "subject_model": [{"value": "ARC", "count": 4}],
            },
            "keyword_preferences": [{"keyword": "多功能工具钳 单手开合", "count": 3}],
        },
        recent_subtitles=[
            {
                "text_final": "ARC 这把多功能工具钳的单手开合很顺。",
                "source_name": "demo1.srt",
            },
            {
                "text_final": "我更在意钳头结构和主刀手感。",
                "source_name": "demo2.srt",
            },
        ],
        content_profile={"subject_type": "多功能工具钳"},
    )

    terms = [item["term"] for item in memory["terms"]]
    summary = summarize_subtitle_review_memory(memory)

    assert "LEATHERMAN" in terms
    assert "ARC" in terms
    assert "多功能工具钳" in terms
    assert any(item["wrong"] == "来泽曼" and item["correct"] == "LEATHERMAN" for item in memory["aliases"])
    assert "同类视频常见表达" in summary


def test_build_subtitle_review_memory_includes_confirmed_feedback_entities():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代Pro UV版",
            "user_feedback": {
                "subject_brand": "Loop 露普",
                "subject_model": "SK05二代Pro UV版",
                "keywords": ["Loop 露普 SK05二代Pro UV版"],
            },
        },
    )

    confirmed = memory["confirmed_entities"][0]
    assert confirmed["brand"] == "Loop露普"
    assert confirmed["model"] == "SK05二代ProUV版"
    assert any(item["wrong"] == "SK零五二代" and item["correct"] == "SK05二代" for item in confirmed["model_aliases"])
    assert any(item["wrong"] == "五眼版" and item["correct"] == "UV版" for item in confirmed["model_aliases"])


def test_build_subtitle_review_memory_uses_auto_confirmed_profile_as_confirmed_subject():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代UV版",
            "review_mode": "auto_confirmed",
            "automation_review": {"auto_confirm": True},
            "search_queries": ["Loop露普 SK05二代UV版"],
        },
    )

    confirmed = memory["confirmed_entities"][0]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert confirmed["brand"] == "Loop露普"
    assert confirmed["model"] == "SK05二代UV版"
    assert ("SK零五", "SK05") in alias_map
    assert ("SK零五二代", "SK05二代") in alias_map
    assert ("五眼版", "UV版") in alias_map


def test_build_subtitle_review_memory_includes_confirmed_entities_from_user_memory():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={
            "confirmed_entities": [
                {
                    "brand": "傲雷",
                    "model": "司令官2Ultra",
                    "phrases": ["傲雷司令官2Ultra", "司令官2Ultra"],
                    "model_aliases": [{"wrong": "司令官2", "correct": "司令官2Ultra"}],
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                }
            ]
        },
        recent_subtitles=[
            {"text_raw": "这次还是手电开箱，重点看 Ultra 版本和流明档位。"},
        ],
        content_profile={
            "subject_type": "EDC手电",
            "content_kind": "unboxing",
        },
    )

    confirmed = memory["confirmed_entities"][0]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert confirmed["brand"] == "傲雷"
    assert confirmed["model"] == "司令官2Ultra"
    assert ("司令官2", "司令官2Ultra") in alias_map


def test_build_subtitle_review_memory_consumes_graph_entities_with_strict_subject_domain_gating():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        subject_domain="edc",
        glossary_terms=[],
        user_memory={
            "entity_graph": {
                "confirmed_entities": [
                    {
                        "brand": "狐蝠工业",
                        "model": "FXX1小副包",
                        "phrases": ["狐蝠工业FXX1小副包", "FXX1小副包"],
                        "brand_aliases": ["鸿福"],
                        "model_aliases": [{"wrong": "F叉二一小副包", "correct": "FXX1小副包"}],
                        "subject_type": "EDC机能包",
                        "subject_domain": "edc",
                    },
                    {
                        "brand": "RunningHub",
                        "model": "无限画布",
                        "phrases": ["RunningHub 无限画布"],
                        "brand_aliases": ["running hub"],
                        "model_aliases": [{"wrong": "无限画板", "correct": "无限画布"}],
                        "subject_type": "AI工作流",
                        "subject_domain": "ai",
                    },
                ],
            },
        },
        recent_subtitles=[{"text_final": "这次包型主要看 FXX1 小副包的仓位和背负。"}],
        content_profile={"subject_type": "EDC机能包", "subject_domain": "edc"},
        include_recent_terms=False,
        include_recent_examples=False,
    )

    terms = {item["term"] for item in memory["terms"]}
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}
    confirmed = {(item["brand"], item["model"]) for item in memory["confirmed_entities"]}

    assert ("狐蝠工业", "FXX1小副包") in confirmed
    assert ("RunningHub", "无限画布") not in confirmed
    assert "狐蝠工业" in terms
    assert "RunningHub" not in terms
    assert ("F叉二一小副包", "FXX1小副包") in alias_map
    assert ("无限画板", "无限画布") not in alias_map


def test_build_subtitle_review_memory_filters_cross_domain_memory_terms_for_edc_context():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={
            "keyword_preferences": [{"keyword": "ComfyUI 工作流", "count": 8}],
            "phrase_preferences": [{"phrase": "RunningHub 无限画布", "count": 6}],
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
        recent_subtitles=[
            {"text_final": "今天这支手电主要看司令官2代的 Ultra 版本、流明和夹持。"},
        ],
        content_profile={
            "subject_type": "EDC手电",
            "content_kind": "unboxing",
        },
        include_recent_terms=False,
        include_recent_examples=False,
    )

    terms = [item["term"] for item in memory["terms"]]
    prompt = build_transcription_prompt(
        source_name="20260209-124735.mp4",
        channel_profile="edc_tactical",
        review_memory=memory,
        dialect_profile="beijing",
    )

    assert "司令官2Ultra" in terms
    assert "ComfyUI" not in terms
    assert "RunningHub" not in terms
    assert "ComfyUI" not in prompt
    assert "RunningHub" not in prompt


def test_build_subtitle_review_memory_respects_explicit_subject_domain_for_mixed_inputs():
    memory = build_subtitle_review_memory(
        channel_profile="tutorial_standard",
        subject_domain="edc",
        glossary_terms=[
            {
                "correct_form": "ComfyUI",
                "wrong_forms": ["康飞UI"],
                "category": "brand",
                "domain": "ai",
            },
            {
                "correct_form": "泛光",
                "wrong_forms": ["反光"],
                "category": "flashlight",
                "domain": "flashlight",
            },
        ],
        user_memory={
            "keyword_preferences": [
                {"keyword": "ComfyUI 工作流", "count": 6},
                {"keyword": "手电 泛光", "count": 4},
            ],
            "phrase_preferences": [
                {"phrase": "RunningHub 无限画布", "count": 5},
                {"phrase": "夜骑补光", "count": 3},
            ],
            "confirmed_entities": [
                {
                    "brand": "RunningHub",
                    "model": "无限画布",
                    "phrases": ["RunningHub 无限画布"],
                    "model_aliases": [{"wrong": "running hub", "correct": "RunningHub"}],
                    "subject_type": "AI工作流",
                    "subject_domain": "ai",
                }
            ],
        },
        recent_subtitles=[
            {"text_final": "这支手电重点看泛光和夜骑补光。"},
            {"text_final": "ComfyUI 工作流和节点编排这期不相关。"},
        ],
        content_profile={"subject_type": "EDC手电", "subject_domain": "edc"},
        include_recent_terms=False,
        include_recent_examples=False,
    )

    terms = {item["term"] for item in memory["terms"]}
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "泛光" in terms
    assert "夜骑补光" in terms
    assert "ComfyUI" not in terms
    assert "RunningHub" not in terms
    assert ("康飞UI", "ComfyUI") not in alias_map
    assert ("running hub", "RunningHub") not in alias_map


def test_build_transcription_prompt_prefers_explicit_subject_domain_over_term_counts():
    prompt = build_transcription_prompt(
        source_name="clip.mp4",
        channel_profile="tutorial_standard",
        review_memory={
            "subject_domain": "edc",
            "terms": [
                {"term": "ComfyUI", "count": 99},
                {"term": "司令官2Ultra", "count": 8},
                {"term": "手电", "count": 6},
            ],
            "aliases": [
                {"wrong": "司令官2", "correct": "司令官2Ultra"},
                {"wrong": "康飞UI", "correct": "ComfyUI"},
            ],
            "confirmed_entities": [
                {"brand": "傲雷", "model": "司令官2Ultra", "phrases": ["傲雷司令官2Ultra"]},
            ],
            "style_examples": [],
        },
    )

    assert "司令官2Ultra" in prompt
    assert "手电" in prompt
    assert "ComfyUI" not in prompt
    assert "康飞UI=ComfyUI" not in prompt


def test_confirmed_subject_overrides_conflicting_builtin_brand_aliases():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[
            {
                "correct_form": "LOOPGEAR",
                "wrong_forms": ["Loop露普", "露普"],
                "category": "flashlight_brand",
            }
        ],
        user_memory={},
        recent_subtitles=[
            {"text_final": "陆虎SK零五二代。"},
            {"text_final": "全新的二代啊五眼版。"},
        ],
        content_profile={
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代UV版",
            "review_mode": "auto_confirmed",
            "automation_review": {"auto_confirm": True},
            "search_queries": ["Loop露普 SK05二代UV版"],
        },
        include_recent_terms=False,
        include_recent_examples=False,
    )

    terms = [item["term"] for item in memory["terms"]]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "LOOPGEAR" not in terms
    assert ("露普", "LOOPGEAR") not in alias_map
    assert apply_domain_term_corrections(
        "陆虎SK零五二代。",
        memory,
        next_text="全新的二代啊五眼版。",
    ) == "Loop露普SK05二代。"
    assert apply_domain_term_corrections(
        "因为SK零五我已经买了。",
        memory,
    ) == "因为SK05我已经买了。"
    assert apply_domain_term_corrections(
        "S四零五都卖了一万多块的序列号我这个二代是四百号其实。",
        memory,
    ) == "SK05都卖了一万多块的序列号我这个二代是四百号其实。"


def test_detect_glossary_domains_returns_tech_for_consumer_electronics_context():
    assert detect_glossary_domains(
        workflow_template="tutorial_standard",
        subtitle_items=[{"text_final": "今天主要讲手机影像、芯片、屏幕和续航表现。"}],
        content_profile={},
        source_name="phone.mp4",
    ) == ["tech"]


def test_detect_glossary_domains_returns_ai_for_ai_workflow_context():
    assert detect_glossary_domains(
        workflow_template="tutorial_standard",
        subtitle_items=[{"text_final": "今天主要演示节点编排、工作流、模型推理和 ComfyUI。"}],
        content_profile={},
        source_name="workflow.mp4",
    ) == ["ai"]


def test_normalize_subject_domain_preserves_legacy_signal_aliases():
    assert normalize_subject_domain("digital") == "tech"
    assert normalize_subject_domain("tech") == "tech"
    assert normalize_subject_domain("ai") == "ai"
    assert normalize_subject_domain("coding") == "ai"
    assert normalize_subject_domain("software") == "ai"


def test_build_transcription_prompt_includes_terms_and_aliases():
    prompt = build_transcription_prompt(
        source_name="arc_review.mp4",
        channel_profile="edc_tactical",
        review_memory={
            "terms": [{"term": "LEATHERMAN"}, {"term": "ARC"}, {"term": "多功能工具钳"}],
            "aliases": [{"wrong": "来自慢", "correct": "LEATHERMAN"}],
            "style_examples": [],
        },
    )

    assert "默认模板" not in prompt
    assert "edc_tactical" not in prompt
    assert "LEATHERMAN" in prompt
    assert "多功能工具钳" in prompt
    assert "来自慢=LEATHERMAN" in prompt


def test_build_transcription_prompt_includes_beijing_dialect_guidance():
    prompt = build_transcription_prompt(
        source_name="cyberdicklang.mp4",
        channel_profile="edc_tactical",
        review_memory={
            "terms": [{"term": "赛博迪克朗"}],
            "aliases": [],
            "style_examples": [],
        },
        dialect_profile="beijing",
    )

    assert "识别口音：北京话" in prompt
    assert "赛博迪克朗" in prompt
    assert "倍儿" in prompt
    assert "甭" in prompt
    assert "儿化音" in prompt


def test_apply_domain_term_corrections_fixes_edc_aliases_and_near_matches():
    corrected = apply_domain_term_corrections(
        "来自慢这把多功能工具前的单手开和和主到都很顺",
        {
            "terms": [
                {"term": "LEATHERMAN"},
                {"term": "多功能工具钳"},
                {"term": "单手开合"},
                {"term": "主刀"},
            ],
            "aliases": [
                {"wrong": "来自慢", "correct": "LEATHERMAN"},
            ],
            "style_examples": [],
        },
    )

    assert "来自慢" in corrected
    assert "多功能工具钳" in corrected
    assert "单手开合" in corrected
    assert "主刀" in corrected


def test_apply_domain_term_corrections_fixes_generic_safe_asr_typos():
    corrected = apply_domain_term_corrections(
        "这个螺四非常执用，后面两个罗丝也很好拆",
        {
            "terms": [{"term": "螺丝"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert corrected == "这个螺丝非常实用，后面两个螺丝也很好拆"


def test_apply_domain_term_corrections_fixes_edc_phrase_typos():
    corrected = apply_domain_term_corrections(
        "美中部组的地方就是这个电路处理，也不是一定要做得经质的华历，这个键变的效果也不错",
        {
            "terms": [{"term": "美中不足"}, {"term": "电镀"}, {"term": "极致华丽"}, {"term": "渐变"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert "美中不足" in corrected
    assert "电镀" in corrected
    assert "极致华丽" in corrected
    assert "渐变" in corrected
    assert "华丽历" not in corrected


def test_apply_domain_term_corrections_does_not_overcorrect_long_config_terms():
    corrected = apply_domain_term_corrections(
        "首先还是这个自定配顶面吧",
        {
          "terms": [{"term": "顶配"}, {"term": "次顶配"}],
          "aliases": [],
          "style_examples": [],
        },
    )

    assert "次顶配" not in corrected


def test_build_transcription_prompt_includes_new_edc_visual_hotword():
    prompt = build_transcription_prompt(
        source_name="mirror_finish.mp4",
        channel_profile="edc_tactical",
        review_memory={
            "terms": [{"term": "镜面"}, {"term": "雾面"}],
            "aliases": [{"wrong": "静面", "correct": "镜面"}],
            "style_examples": [],
        },
    )

    assert "镜面" in prompt
    assert "静面=镜面" in prompt


def test_apply_domain_term_corrections_fixes_jingmian_typos():
    corrected = apply_domain_term_corrections(
        "这个静面效果确实更亮，净面处理也更显质感。",
        {
            "terms": [{"term": "镜面"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert "静面" not in corrected
    assert "净面" not in corrected
    assert corrected.count("镜面") == 2


def test_apply_domain_term_corrections_fixes_edc_flashlight_terms():
    corrected = apply_domain_term_corrections(
        "这期手机评测里我会聊K线、背针孔、胶丝，还有即ed的玩法，黑金好，最后拿起来提高山山。",
        {
            "terms": [
                {"term": "手电评测"},
                {"term": "K鞘"},
                {"term": "尾绳孔"},
                {"term": "胶塞儿"},
                {"term": "即EDC"},
                {"term": "非常好"},
                {"term": "金光闪闪"},
            ],
            "aliases": [
                {"wrong": "手机评测", "correct": "手电评测"},
                {"wrong": "K线", "correct": "K鞘"},
                {"wrong": "背针孔", "correct": "尾绳孔"},
                {"wrong": "胶丝", "correct": "胶塞儿"},
                {"wrong": "即ed", "correct": "即EDC"},
                {"wrong": "黑金好", "correct": "非常好"},
                {"wrong": "提高山山", "correct": "金光闪闪"},
            ],
            "style_examples": [],
        },
    )

    assert "手电评测" in corrected
    assert "K鞘" in corrected
    assert "尾绳孔" in corrected
    assert "胶塞儿" in corrected
    assert "即EDC" in corrected
    assert "非常好" in corrected
    assert "金光闪闪" in corrected


def test_build_subtitle_review_memory_injects_default_edc_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "EDC" in terms
    assert "FAS" in terms
    assert "贴片" in terms
    assert any(item["correct"] == "极致华丽" for item in memory["aliases"])


def test_build_subtitle_review_memory_expands_edc_subdomains():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个手电的泛光和色温更稳，旁边那把折刀背夹也做得更细。"}],
        content_profile={"video_theme": "EDC手电和折刀开箱评测"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "手电" in terms
    assert "泛光" in terms
    assert "折刀" in terms
    assert "背夹" in terms


def test_build_subtitle_review_memory_includes_edc_flashlight_variant_alias():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个手电的V湖眼版和UV版我都拿到了。"}],
        content_profile={"video_theme": "EDC手电开箱评测"},
    )

    assert any(item["term"] == "微弧版" for item in memory["terms"])
    assert any(item["wrong"] == "V湖眼版" and item["correct"] == "微弧版" for item in memory["aliases"])


def test_build_subtitle_review_memory_includes_new_flashlight_aliases():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这期手机评测里我顺手讲一下K线、背针孔和胶丝。"}],
        content_profile={"video_theme": "EDC手电开箱评测"},
    )

    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert ("手机评测", "手电评测") in alias_map
    assert ("K线", "K鞘") in alias_map
    assert ("背针孔", "尾绳孔") in alias_map
    assert ("胶丝", "胶塞儿") in alias_map


def test_build_subtitle_review_memory_includes_vhu_variants_for_flashlight_context():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "之前那个V湖的包括现在这个二代我都拿到了。"}],
        content_profile={"video_theme": "EDC手电开箱评测"},
    )

    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert ("V湖的", "微弧版") in alias_map


def test_build_subtitle_review_memory_includes_domestic_edc_brand_clusters():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这期从 tomtoc 机能包、纳拓工具钳、菲尼克斯手电到 Kizer 折刀都一起聊一下。"}],
        content_profile={"video_theme": "EDC机能包手电工具钳折刀开箱评测"},
    )

    terms = {item["term"] for item in memory["terms"]}
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "TOMTOC" in terms
    assert "NEXTOOL" in terms
    assert "FENIX" in terms
    assert "KIZER" in terms
    assert ("纳拓", "NEXTOOL") in alias_map
    assert ("菲尼克斯", "FENIX") in alias_map
    assert ("Kizer", "KIZER") in alias_map


def test_build_subtitle_review_memory_includes_bag_domain_keywords():
    memory = build_subtitle_review_memory(
        channel_profile="unboxing_default",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个胸包和快取包我最近在 tomtoc 和 PGYTECH 之间纠结。"}],
        content_profile={"video_theme": "机能包开箱评测"},
    )

    terms = {item["term"] for item in memory["terms"]}

    assert "机能包" in terms
    assert "胸包" in terms
    assert "TOMTOC" in terms
    assert "PGYTECH" in terms


def test_build_subtitle_review_memory_includes_new_mainstream_edc_brand_clusters():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[
            {
                "text_final": "这期把 FOXBAT、FIRST WOLF、psiger、LiiGear、SOG、华尔纳、顺全、Maxace、世界 mundus 和 Microtech 一起聊了。"
            }
        ],
        content_profile={"video_theme": "EDC机能包工具钳折刀开箱评测"},
    )

    terms = {item["term"] for item in memory["terms"]}
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "狐蝠工业" in terms
    assert "头狼工业" in terms
    assert "PSIGEAR" in terms
    assert "LIIGEAR" in terms
    assert "SOG" in terms
    assert "WARNA" in terms
    assert "SQT顺全作" in terms
    assert "MAXACE" in terms
    assert "MUNDUS" in terms
    assert "MICROTECH" in terms
    assert ("FIRST WOLF", "头狼工业") in alias_map
    assert ("psiger", "PSIGEAR") in alias_map
    assert ("华尔纳", "WARNA") in alias_map
    assert ("顺全", "SQT顺全作") in alias_map
    assert ("世界 mundus", "MUNDUS") in alias_map
    assert ("Microtech", "MICROTECH") in alias_map


def test_build_subtitle_review_memory_includes_discovered_flashlight_and_tool_brands():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这回顺手对比了凯瑞兹、务本和戈博。"}],
        content_profile={"video_theme": "EDC手电工具开箱评测"},
    )

    terms = {item["term"] for item in memory["terms"]}
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "KLARUS" in terms
    assert "WUBEN" in terms
    assert "GERBER" in terms
    assert ("凯瑞兹", "KLARUS") in alias_map
    assert ("务本", "WUBEN") in alias_map
    assert ("戈博", "GERBER") in alias_map


def test_build_subtitle_review_memory_injects_ai_and_tech_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="screen_tutorial",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个 AI 工作流里要先调提示词，再看 RAG 命中。"}],
        content_profile={"video_theme": "AI工作流搭建教程"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "提示词" in terms
    assert "RAG" in terms
    assert "工作流" in terms
    assert "RunningHub" in terms


def test_build_subtitle_review_memory_injects_coding_with_adjacent_ai_tech_terms():
    memory = build_subtitle_review_memory(
        channel_profile="screen_tutorial",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个接口调试完之后，再把代码提交到仓库。"}],
        content_profile={"video_theme": "AI 编程工作流实战"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "接口" in terms
    assert "代码" in terms
    assert "工作流" in terms
    assert "提示词" in terms


def test_build_subtitle_review_memory_injects_ai_creator_hotwords():
    memory = build_subtitle_review_memory(
        channel_profile="screen_tutorial",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "RunningHub 的无限画布拿来搭漫剧工作流，ComfyUI 和 OpenClaw 也能接进来。"}],
        content_profile={"video_theme": "RunningHub 无限画布漫剧工作流演示"},
    )

    terms = [item["term"] for item in memory["terms"]]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "RunningHub" in terms
    assert "ComfyUI" in terms
    assert "OpenClaw" in terms
    assert "无限画布" in terms
    assert ("running hub", "RunningHub") in alias_map
    assert ("RH", "RunningHub") in alias_map


def test_detect_glossary_domains_keeps_no_signal_input_empty():
    domains = detect_glossary_domains(
        workflow_template=None,
        content_profile=None,
        subtitle_items=[],
        source_name="20260209-124735.mp4",
    )

    assert domains == []


def test_detect_glossary_domains_does_not_treat_workflow_template_as_domain_signal():
    domains = detect_glossary_domains(
        workflow_template="unboxing_standard",
        content_profile={},
        subtitle_items=[],
        source_name="demo.mp4",
    )

    assert domains == []


def test_detect_glossary_domains_returns_canonical_domains_from_content_evidence():
    assert detect_glossary_domains(
        workflow_template="unboxing_standard",
        content_profile={},
        subtitle_items=[{"text_final": "今天主要演示节点编排、工作流和模型推理。"}],
        source_name="demo.mp4",
    ) == ["ai"]

    assert detect_glossary_domains(
        workflow_template="unboxing_standard",
        content_profile={},
        subtitle_items=[{"text_final": "这次重点看机能包的分仓、挂点和通勤穿搭。"}],
        source_name="bag.mp4",
    ) == ["functional"]

    assert detect_glossary_domains(
        workflow_template="unboxing_standard",
        content_profile={},
        subtitle_items=[{"text_final": "今天开箱这把工具钳，重点看钳头、批头和螺丝刀。"}],
        source_name="tool.mp4",
    ) == ["tools"]


def test_build_subtitle_review_memory_does_not_inject_ai_terms_without_domain_signal():
    memory = build_subtitle_review_memory(
        channel_profile=None,
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "ComfyUI" not in terms
    assert "RunningHub" not in terms
    assert "OpenClaw" not in terms


def test_build_subtitle_review_memory_does_not_inject_builtin_terms_from_template_alone():
    memory = build_subtitle_review_memory(
        channel_profile="tutorial_standard",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "ComfyUI" not in terms
    assert "RunningHub" not in terms
    assert "芯片" not in terms


def test_build_subtitle_review_memory_does_not_apply_workflow_template_scoped_terms_for_correction():
    memory = build_subtitle_review_memory(
        channel_profile="tutorial_standard",
        glossary_terms=[
            {
                "scope_type": "workflow_template",
                "scope_value": "tutorial_standard",
                "correct_form": "ComfyUI",
                "wrong_forms": ["康飞UI"],
                "category": "brand",
            }
        ],
        user_memory={},
        recent_subtitles=[],
        content_profile={},
    )

    terms = [item["term"] for item in memory["terms"]]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "ComfyUI" not in terms
    assert ("康飞UI", "ComfyUI") not in alias_map


def test_build_subtitle_review_memory_injects_food_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="food_explore",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这家店锅气很足，回甘也很干净。"}],
        content_profile={"video_theme": "探店试吃"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "锅气" in terms
    assert "回甘" in terms
    assert "探店" in terms


def test_build_subtitle_review_memory_injects_finance_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="market_watch",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "美联储如果继续降息，市场会继续看通胀和财报。"}],
        content_profile={"video_theme": "美股与宏观财经快评"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "美联储" in terms
    assert "降息" in terms
    assert "通胀" in terms
    assert "财报" in terms


def test_build_subtitle_review_memory_injects_news_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="news_briefing",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "外媒关注峰会后的局势变化，联合国也给出了新的表态。"}],
        content_profile={"video_theme": "国际新闻速览"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "国际新闻" in terms
    assert "外媒" in terms
    assert "峰会" in terms
    assert "联合国" in terms


def test_build_subtitle_review_memory_injects_sports_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="sports_highlight",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这场季后赛最后靠三分绝杀，篮板和助攻也都拉满了。"}],
        content_profile={"video_theme": "体育赛事复盘"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "季后赛" in terms
    assert "三分" in terms
    assert "绝杀" in terms
    assert "助攻" in terms


def test_build_subtitle_review_memory_prioritizes_aliases_for_ranked_terms():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert ("法斯", "FAS") in alias_map
    assert any(correct == "极致华丽" for _, correct in alias_map)


def test_build_subtitle_review_memory_promotes_recent_edc_correction_aliases():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={
            "recent_corrections": [
                {
                    "field_name": "video_theme",
                    "original_value": "刚马镜面折刀开箱",
                    "corrected_value": "钢马镜面折刀开箱",
                    "source_name": "demo.mp4",
                }
            ],
            "field_preferences": {},
            "keyword_preferences": [],
        },
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}
    terms = [item["term"] for item in memory["terms"]]

    assert ("刚马镜面折刀开箱", "钢马镜面折刀开箱") in alias_map
    assert "钢马镜面折刀开箱" in terms


def test_build_subtitle_review_memory_uses_phrase_preferences_as_learning_memory():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={
            "phrase_preferences": [
                {"phrase": "次顶配镜面", "count": 5},
            ],
            "style_preferences": [
                {"tag": "detail_focused", "count": 2, "example": "细节和工艺这次都拉满"},
            ],
        },
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "次顶配镜面" in terms
    assert memory["style_preferences"][0]["tag"] == "detail_focused"


def test_build_subtitle_review_memory_promotes_compound_domain_phrases_from_context():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这次顶配镜面和雾面版本放一起看差别更明显。"}],
        content_profile={"subject_type": "EDC折刀", "summary": "次顶配镜面更亮"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "次顶配镜面" in terms


def test_apply_domain_term_corrections_prefers_compound_domain_phrase_when_available():
    corrected = apply_domain_term_corrections(
        "这个次定配静面看起来会更亮一点",
        {
            "terms": [{"term": "次顶配镜面"}, {"term": "次顶配"}, {"term": "镜面"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert "次顶配镜面" in corrected
    assert "次定配" not in corrected
    assert "静面" not in corrected


def test_apply_domain_term_corrections_repairs_truncated_latin_brand_token():
    corrected = apply_domain_term_corrections(
        "折刀开箱,FAS,LEATHER",
        {
            "terms": [{"term": "LEATHERMAN"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert corrected == "折刀开箱,FAS,LEATHER"


def test_apply_domain_term_corrections_does_not_force_brand_to_canonical_name():
    corrected = apply_domain_term_corrections(
        "莱德曼这个工具钳手感还行，纳拓那把之前也买过。",
        {
            "terms": [{"term": "LEATHERMAN"}, {"term": "OLIGHT"}],
            "aliases": [
                {"wrong": "傲雷", "correct": "OLIGHT", "category": "edc_brand"},
                {"wrong": "来自慢", "correct": "LEATHERMAN", "category": "edc_brand"},
            ],
            "style_examples": [],
        },
    )

    assert "LEATHERMAN" not in corrected
    assert "OLIGHT" not in corrected
    assert "莱德曼" in corrected
    assert "纳拓" in corrected


def test_apply_domain_term_corrections_uses_confirmed_feedback_anchor_for_current_episode():
    corrected = apply_domain_term_corrections(
        "呃陆虎SK零五二代。全新的二代啊五眼版。",
        {
            "terms": [{"term": "Loop露普"}, {"term": "SK05二代"}],
            "aliases": [],
            "style_examples": [],
            "confirmed_entities": [
                {
                    "brand": "Loop露普",
                    "model": "SK05二代ProUV版",
                    "model_aliases": [
                        {"wrong": "SK零五二代", "correct": "SK05二代"},
                        {"wrong": "五眼版", "correct": "UV版"},
                    ],
                }
            ],
        },
        prev_text="呃Loop露普SK05二代。",
    )

    assert "陆虎" not in corrected
    assert "Loop露普SK05二代" in corrected
    assert "UV版" in corrected


def test_apply_domain_term_corrections_repairs_wrong_brand_before_canonical_model_anchor():
    corrected = apply_domain_term_corrections(
        "这个是陆虎SK05二代。",
        {
            "terms": [{"term": "Loop露普"}, {"term": "SK05二代"}],
            "aliases": [],
            "style_examples": [],
            "confirmed_entities": [
                {
                    "brand": "Loop露普",
                    "model": "SK05二代ProUV版",
                    "model_aliases": [
                        {"wrong": "SK零五二代", "correct": "SK05二代"},
                    ],
                }
            ],
        },
    )

    assert corrected == "这个是Loop露普SK05二代。"


def test_apply_domain_term_corrections_requires_current_anchor_for_graph_brand_alias():
    corrected = apply_domain_term_corrections(
        "鸿福这包其实收纳还行。",
        {
            "terms": [{"term": "狐蝠工业"}, {"term": "FXX1小副包"}],
            "aliases": [],
            "style_examples": [],
            "confirmed_entities": [
                {
                    "brand": "狐蝠工业",
                    "model": "FXX1小副包",
                    "phrases": ["狐蝠工业FXX1小副包", "FXX1小副包"],
                    "brand_aliases": ["鸿福"],
                    "model_aliases": [{"wrong": "F叉二一小副包", "correct": "FXX1小副包"}],
                }
            ],
        },
        prev_text="这次聊一个通勤小包。",
        next_text="重点还是看背负。",
    )

    assert corrected == "鸿福这包其实收纳还行。"


def test_apply_domain_term_corrections_replaces_graph_brand_alias_with_current_model_anchor():
    corrected = apply_domain_term_corrections(
        "鸿福FXX1小副包这次把拉链也换了。",
        {
            "terms": [{"term": "狐蝠工业"}, {"term": "FXX1小副包"}],
            "aliases": [],
            "style_examples": [],
            "confirmed_entities": [
                {
                    "brand": "狐蝠工业",
                    "model": "FXX1小副包",
                    "phrases": ["狐蝠工业FXX1小副包", "FXX1小副包"],
                    "brand_aliases": ["鸿福"],
                    "model_aliases": [{"wrong": "F叉二一小副包", "correct": "FXX1小副包"}],
                }
            ],
        },
    )

    assert corrected == "狐蝠工业FXX1小副包这次把拉链也换了。"


def test_apply_domain_term_corrections_suppresses_negative_memory_alias_even_with_anchor():
    corrected = apply_domain_term_corrections(
        "鸿福FXX1小副包这次把拉链也换了。",
        {
            "terms": [{"term": "狐蝠工业"}, {"term": "FXX1小副包"}],
            "aliases": [],
            "style_examples": [],
            "negative_alias_pairs": [
                {"field_name": "subject_brand", "alias_value": "鸿福", "canonical_value": "狐蝠工业"},
            ],
            "confirmed_entities": [
                {
                    "brand": "狐蝠工业",
                    "model": "FXX1小副包",
                    "phrases": ["狐蝠工业FXX1小副包", "FXX1小副包"],
                    "brand_aliases": ["鸿福"],
                    "model_aliases": [{"wrong": "F叉二一小副包", "correct": "FXX1小副包"}],
                }
            ],
        },
    )

    assert corrected == "鸿福FXX1小副包这次把拉链也换了。"


def test_apply_domain_term_corrections_keeps_wuyanban_without_local_context_support():
    corrected = apply_domain_term_corrections(
        "全新的二代啊五眼版。",
        {
            "terms": [{"term": "Loop露普"}, {"term": "SK05二代"}],
            "aliases": [],
            "style_examples": [],
            "confirmed_entities": [
                {
                    "brand": "Loop露普",
                    "model": "SK05二代ProUV版",
                    "model_aliases": [
                        {"wrong": "五眼版", "correct": "UV版"},
                    ],
                }
            ],
        },
        prev_text="这玩意儿刚到手。",
        next_text="包装小了一圈。",
    )

    assert "五眼版" in corrected
    assert "UV版" not in corrected
