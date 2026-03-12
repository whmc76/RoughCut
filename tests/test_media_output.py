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
    )

    canonical = output_mod.get_cover_manifest_path(output_path)
    legacy = output_mod.get_legacy_cover_manifest_path(output_path)

    assert canonical.exists()
    assert legacy.exists()
    assert json.loads(canonical.read_text(encoding="utf-8")) == json.loads(legacy.read_text(encoding="utf-8"))


def test_sanitize_generated_cover_title_rejects_foreign_brand():
    sanitized = output_mod._sanitize_generated_cover_title(
        {"top": "LEATHERMAN", "main": "ARC深雕版", "bottom": "360度无死角雕刻"},
        fallback_plan={"top": "REATE", "main": "折刀雕刻开箱", "bottom": "先看柄身细节"},
        content_profile={"subject_brand": "REATE", "subject_type": "EDC折刀", "visible_text": "REATE"},
    )

    assert sanitized == {"top": "REATE", "main": "折刀雕刻开箱", "bottom": "先看柄身细节"}
