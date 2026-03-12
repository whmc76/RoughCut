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


def test_build_cover_safe_area_layers_adds_bottom_mask_when_bottom_title_exists():
    layers = output_mod._build_cover_safe_area_layers({"top": "REATE", "main": "折刀", "bottom": "先看雕刻细节"})

    assert len(layers) == 2
    assert all(layer.startswith("drawbox=") for layer in layers)
    assert "y=ih*0.74" in layers[0]


def test_build_cover_safe_area_layers_skips_mask_without_bottom_title():
    layers = output_mod._build_cover_safe_area_layers({"top": "REATE", "main": "折刀", "bottom": ""})

    assert layers == []
