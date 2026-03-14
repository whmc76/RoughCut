from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import roughcut.media.output as output_mod


def test_get_output_project_dir_creates_per_job_folder(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        output_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(tmp_path), output_name_pattern="{date}_{stem}"),
    )

    project_dir = output_mod.get_output_project_dir("demo.mp4", datetime(2026, 3, 12, 8, 0, 0))

    assert project_dir == tmp_path / "20260312_demo"
    assert project_dir.exists()
    assert project_dir.is_dir()


def test_build_cover_variant_output_path_includes_version_and_strategy(tmp_path: Path):
    path = output_mod.build_cover_variant_output_path(tmp_path / "demo_cover.jpg", 1, "bilibili")

    assert path.name == "demo_cover_v2_bilibili.jpg"


def test_write_cover_variant_manifest_writes_canonical_and_legacy_names(tmp_path: Path):
    output_path = tmp_path / "demo_cover.jpg"
    variant_path = tmp_path / "demo_cover_v1_xiaohongshu.jpg"
    variant_path.write_bytes(b"cover")

    output_mod._write_cover_variant_manifest(
        output_path,
        selected=[{"seek": 12.34}],
        title_variants=[
            {
                "strategy_key": "xiaohongshu",
                "strategy_label": "小红书吸睛",
                "reason": "主体最完整",
                "title_style": "double_banner",
                "title": {"top": "LEATHERMAN", "main": "ARC", "bottom": "这次升级到位吗"},
            }
        ],
        outputs=[variant_path],
        rankings=[{"index": 3, "score": 0.92, "reason": "主体最完整", "source": "llm_rank"}],
        selection_summary={
            "review_recommended": False,
            "score_gap": 0.12,
            "review_reason": "",
        },
    )

    canonical = output_mod.get_cover_manifest_path(output_path)
    legacy = output_mod.get_legacy_cover_manifest_path(output_path)

    assert canonical.exists()
    assert legacy.exists()
    assert json.loads(canonical.read_text(encoding="utf-8")) == json.loads(legacy.read_text(encoding="utf-8"))
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert payload[0]["score"] == 0.92
    assert payload[0]["is_primary"] is True


def test_build_cover_selection_summary_requests_review_when_gap_is_small(monkeypatch):
    monkeypatch.setattr(
        output_mod,
        "get_settings",
        lambda: SimpleNamespace(auto_select_cover_variant=True, cover_selection_review_gap=0.08),
    )

    summary = output_mod._build_cover_selection_summary(
        [
            {"index": 4, "score": 0.91},
            {"index": 7, "score": 0.86},
        ]
    )

    assert summary["selected_variant_index"] == 1
    assert summary["runner_up_index"] == 2
    assert summary["review_recommended"] is True
    assert summary["score_gap"] == 0.05


def test_load_cover_selection_summary_reads_primary_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        output_mod,
        "get_settings",
        lambda: SimpleNamespace(auto_select_cover_variant=True, cover_selection_review_gap=0.08),
    )
    output_path = tmp_path / "demo_cover.jpg"
    output_mod.get_cover_manifest_path(output_path).write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "path": str(tmp_path / "demo_cover_v1.jpg"),
                    "score": 0.88,
                    "is_primary": True,
                    "review_recommended": True,
                    "score_gap_to_next": 0.03,
                    "review_reason": "前两张封面分差过小，建议确认首选图。",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = output_mod.load_cover_selection_summary(output_path)

    assert summary == {
        "enabled": True,
        "review_recommended": True,
        "selected_variant_index": 1,
        "selected_score": 0.88,
        "score_gap": 0.03,
        "review_reason": "前两张封面分差过小，建议确认首选图。",
    }


def test_sanitize_generated_cover_title_rejects_foreign_brand():
    sanitized = output_mod._sanitize_generated_cover_title(
        {"top": "LEATHERMAN", "main": "ARC深雕版", "bottom": "360度无死角雕刻"},
        fallback_plan={"top": "REATE", "main": "折刀雕刻开箱", "bottom": "先看柄身细节"},
        content_profile={"subject_brand": "REATE", "subject_type": "EDC折刀", "visible_text": "REATE"},
    )

    assert sanitized == {"top": "REATE", "main": "折刀雕刻开箱", "bottom": "先看柄身细节"}


def test_sanitize_generated_cover_title_rejects_missing_required_ai_topic():
    sanitized = output_mod._sanitize_generated_cover_title(
        {"top": "教程", "main": "软件工具", "bottom": "这功能太强了"},
        fallback_plan={"top": "RUNNINGHUB", "main": "无限画布", "bottom": "新功能刚上线"},
        content_profile={
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "video_theme": "RunningHub 无限画布新功能上线与实操演示",
        },
    )

    assert sanitized == {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "新功能刚上线"}


def test_adapt_cover_title_for_strategy_applies_platform_bias_to_bottom():
    fallback = {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "这功能强得离谱"}
    profile = {
        "subject_brand": "RunningHub",
        "subject_model": "无限画布",
        "subject_type": "AI工作流创作平台",
        "copy_style": "attention_grabbing",
    }

    bilibili = output_mod._adapt_cover_title_for_strategy(fallback, strategy_key="bilibili", content_profile=profile)
    xiaohongshu = output_mod._adapt_cover_title_for_strategy(fallback, strategy_key="xiaohongshu", content_profile=profile)
    ctr = output_mod._adapt_cover_title_for_strategy(fallback, strategy_key="ctr", content_profile=profile)
    brand = output_mod._adapt_cover_title_for_strategy(fallback, strategy_key="brand", content_profile=profile)

    assert bilibili == {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "无限画布一口气讲透"}
    assert xiaohongshu == {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "无限画布细节直接封神"}
    assert ctr == {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "无限画布这次太炸了"}
    assert brand == {"top": "RUNNINGHUB", "main": "无限画布", "bottom": "无限画布高级感拉满"}


def test_build_cover_safe_area_layers_keeps_cover_clean_even_with_bottom_title():
    layers = output_mod._build_cover_safe_area_layers({"top": "REATE", "main": "折刀", "bottom": "先看雕刻细节"})

    assert layers == []


def test_build_cover_safe_area_layers_skips_mask_without_bottom_title():
    layers = output_mod._build_cover_safe_area_layers({"top": "REATE", "main": "折刀", "bottom": ""})

    assert layers == []


def test_build_cover_candidate_seeks_biases_sampling_away_from_intro():
    seeks = output_mod._build_cover_candidate_seeks(120.0, candidate_count=5, anchor_seek=8.0)

    assert len(seeks) == 5
    assert seeks == sorted(seeks)
    assert min(seeks) >= 18.0
    assert max(seeks) <= 105.6


def test_title_style_tokens_clamp_text_into_cross_platform_safe_zone():
    style = output_mod._title_style_tokens(
        "double_banner",
        title_lines={"top": "REATE", "main": "彩雕折刀", "bottom": "先看细节"},
        cover_style="tech_showcase",
    )

    assert style["top"]["x"].startswith("max(max(w*0.234375")
    assert "min((w-text_w)/2" in style["top"]["x"]
    assert style["main"]["x"].startswith("max(max(w*0.234375")
    assert "min((w-text_w)/2" in style["main"]["x"]
    assert style["main"]["y"].startswith("max(max(h*0.120")
    assert "min((h-text_h)/2" in style["main"]["y"]
    assert style["bottom"]["y"].startswith("max(max(h*0.120")
    assert "h-max(h*0.140" in style["bottom"]["y"]


def test_prioritize_cover_variants_promotes_ctr_for_portrait():
    selected, rankings, plans = output_mod._prioritize_cover_variants(
        selected=[{"seek": 12.0}, {"seek": 22.0}, {"seek": 32.0}],
        selected_rankings=[
            {"index": 0, "score": 0.82},
            {"index": 1, "score": 0.76},
            {"index": 2, "score": 0.64},
        ],
        title_variants=[
            {"strategy_key": "xiaohongshu"},
            {"strategy_key": "bilibili"},
            {"strategy_key": "ctr"},
        ],
        is_portrait=True,
    )

    assert selected[0]["seek"] == 32.0
    assert rankings[0]["score"] == 0.86
    assert plans[0]["strategy_key"] == "ctr"


def test_fit_cover_text_to_safe_zone_shrinks_long_main_title():
    fitted = output_mod._fit_cover_text_to_safe_zone(
        "这把折刀的彩雕细节真的太夸张了",
        170,
        min_size=72,
    )

    assert fitted < 170
    assert fitted >= 72


def test_fit_cover_text_to_safe_zone_accounts_for_box_padding():
    plain = output_mod._fit_cover_text_to_safe_zone("REATE", 84, min_size=56)
    boxed = output_mod._fit_cover_text_to_safe_zone("REATE", 84, min_size=56, box_padding=20)

    assert boxed <= plain


def test_drawtext_escapes_commas_in_safe_zone_expressions():
    layer = output_mod._drawtext(
        text="REATE",
        fontfile="C\\:/Windows/Fonts/msyhbd.ttc",
        fontsize=84,
        fontcolor="0xFFFFFFFF",
        bordercolor="0x111111FF",
        borderw=6,
        x="max(370,min((w-text_w)/2,910-text_w))",
        y="max(86,min(h-text_h-84,620-text_h))",
    )

    assert ":x=max(370\\,min((w-text_w)/2\\,910-text_w))" in layer
    assert ":y=max(86\\,min(h-text_h-84\\,620-text_h))" in layer
