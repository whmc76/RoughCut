from __future__ import annotations

import json
from pathlib import Path

from roughcut.review import intelligent_copy as intelligent_copy_module
from roughcut.review.intelligent_copy import promote_platform_preview_to_intelligent_copy_result
from roughcut.review.intelligent_copy import upgrade_existing_intelligent_copy_result


def test_promote_platform_preview_updates_canonical_smart_copy_sources(tmp_path: Path) -> None:
    folder = tmp_path / "case"
    material_dir = folder / "smart-copy"
    meta_dir = material_dir / "_meta"
    copy_dir = material_dir / "_copy"
    meta_dir.mkdir(parents=True)
    copy_dir.mkdir(parents=True)

    existing_result = {
        "platforms": [
            {
                "key": "bilibili",
                "label": "B站",
                "titles": ["旧标题"],
                "primary_title": "旧标题",
                "body": "旧正文",
                "tags": ["旧标签"],
                "constraints": {},
                "title_label": "标题",
                "body_label": "简介",
                "tag_label": "标签",
                "copy_material": {"primary_title": "旧标题", "body": "旧正文", "tags": ["旧标签"]},
                "category": "生活兴趣/户外潮流",
                "collection": {"name": "EDC刀光火工具集"},
                "scheduled_publish_at": "2026-06-07T19:30",
            },
            {
                "key": "xiaohongshu",
                "label": "小红书",
                "titles": ["小红书旧标题"],
                "primary_title": "小红书旧标题",
                "body": "小红书旧正文",
                "tags": ["小红书旧标签"],
                "constraints": {},
                "title_label": "标题",
                "body_label": "正文",
                "tag_label": "话题",
            },
        ],
        "cover_matrix": {},
    }
    packaging = {
        "highlights": {"product": "MAXACE美杜莎4"},
        "platforms": {
            "bilibili": {
                "titles": ["旧标题"],
                "description": "旧正文",
                "tags": ["旧标签"],
                "category": "生活兴趣/户外潮流",
                "collection": {"name": "EDC刀光火工具集"},
                "scheduled_publish_at": "2026-06-07T19:30",
            },
            "xiaohongshu": {
                "titles": ["小红书旧标题"],
                "description": "小红书旧正文",
                "tags": ["小红书旧标签"],
            },
        },
    }
    (meta_dir / "smart-copy.json").write_text(json.dumps(existing_result, ensure_ascii=False, indent=2), encoding="utf-8")
    (meta_dir / "platform-packaging.json").write_text(json.dumps(packaging, ensure_ascii=False, indent=2), encoding="utf-8")
    (copy_dir / "01-bilibili-titles.txt").write_text("1. 旧标题\n", encoding="utf-8")
    (copy_dir / "01-bilibili-body.txt").write_text("旧正文\n", encoding="utf-8")
    (copy_dir / "01-bilibili-tags.txt").write_text("旧标签\n", encoding="utf-8")
    (copy_dir / "02-xiaohongshu-titles.txt").write_text("1. 小红书旧标题\n", encoding="utf-8")
    (copy_dir / "02-xiaohongshu-body.txt").write_text("小红书旧正文\n", encoding="utf-8")
    (copy_dir / "02-xiaohongshu-tags.txt").write_text("小红书旧标签\n", encoding="utf-8")

    preview_path = tmp_path / "preview.json"
    preview_path.write_text(
        json.dumps(
            {
                "platforms": {
                    "bilibili": {
                        "titles": ["新标题一", "新标题二"],
                        "description": "新正文",
                        "tags": ["新标签A", "新标签B"],
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = promote_platform_preview_to_intelligent_copy_result(
        str(folder),
        preview_path=str(preview_path),
        platforms=["bilibili"],
    )

    updated_packaging = json.loads((meta_dir / "platform-packaging.json").read_text(encoding="utf-8"))
    assert updated_packaging["platforms"]["bilibili"]["titles"][0] == "新标题一"
    assert updated_packaging["platforms"]["bilibili"]["description"] == "新正文"
    assert updated_packaging["platforms"]["bilibili"]["collection"]["name"] == "EDC刀光火工具集"
    assert updated_packaging["platforms"]["xiaohongshu"]["description"] == "小红书旧正文"

    assert "新标题一" in (copy_dir / "01-bilibili-titles.txt").read_text(encoding="utf-8")
    assert (copy_dir / "01-bilibili-body.txt").read_text(encoding="utf-8").strip() == "新正文"
    assert "新标签A" in (copy_dir / "01-bilibili-tags.txt").read_text(encoding="utf-8")
    assert (copy_dir / "02-xiaohongshu-body.txt").read_text(encoding="utf-8").strip() == "小红书旧正文"

    bilibili_result = next(item for item in result["platforms"] if item["key"] == "bilibili")
    assert bilibili_result["primary_title"] == "新标题一"
    assert bilibili_result["body"] == "新正文"


def test_promote_platform_preview_rebuilds_publication_metadata_from_creator_context(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "case"
    material_dir = folder / "smart-copy"
    meta_dir = material_dir / "_meta"
    copy_dir = material_dir / "_copy"
    meta_dir.mkdir(parents=True)
    copy_dir.mkdir(parents=True)

    existing_result = {
        "platforms": [
            {
                "key": "douyin",
                "label": "抖音",
                "titles": ["旧标题"],
                "primary_title": "旧标题",
                "body": "旧正文",
                "tags": ["旧标签"],
                "constraints": {},
                "title_label": "标题",
                "body_label": "描述",
                "tag_label": "标签",
            },
        ],
        "cover_matrix": {},
    }
    packaging = {
        "highlights": {"product": "MAXACE美杜莎4"},
        "platforms": {
            "douyin": {
                "titles": ["旧标题"],
                "description": "旧正文",
                "tags": ["旧标签"],
            },
        },
    }
    (meta_dir / "smart-copy.json").write_text(json.dumps(existing_result, ensure_ascii=False, indent=2), encoding="utf-8")
    (meta_dir / "platform-packaging.json").write_text(json.dumps(packaging, ensure_ascii=False, indent=2), encoding="utf-8")
    (copy_dir / "03-douyin-titles.txt").write_text("1. 旧标题\n", encoding="utf-8")
    (copy_dir / "03-douyin-body.txt").write_text("旧正文\n", encoding="utf-8")
    (copy_dir / "03-douyin-tags.txt").write_text("旧标签\n", encoding="utf-8")

    preview_path = tmp_path / "douyin-preview.json"
    preview_path.write_text(
        json.dumps(
            {
                "platforms": {
                    "douyin": {
                        "titles": ["抖音新标题"],
                        "description": "抖音新正文",
                        "tags": ["新标签A", "新标签B"],
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def _fake_resolve_upgrade_platform_options(**kwargs):
        return {
            "douyin": {
                "scheduled_publish_at": "2026-06-07T20:30",
                "collection_name": "EDC刀光火工具集",
                "platform_specific_overrides": {
                    "collection_management": {
                        "status": "select_existing",
                        "target_collection_name": "EDC刀光火工具集",
                        "selected_collection_name": "EDC刀光火工具集",
                    }
                },
            }
        }

    monkeypatch.setattr(
        intelligent_copy_module,
        "_resolve_upgrade_platform_options",
        _fake_resolve_upgrade_platform_options,
    )

    result = promote_platform_preview_to_intelligent_copy_result(
        str(folder),
        preview_path=str(preview_path),
        platforms=["douyin"],
        creator_profile_id="creator-123",
        creator_profile_name="FAS",
    )

    updated_packaging = json.loads((meta_dir / "platform-packaging.json").read_text(encoding="utf-8"))
    douyin_entry = updated_packaging["platforms"]["douyin"]
    assert douyin_entry["description"] == "抖音新正文"
    assert douyin_entry["scheduled_publish_at"] == "2026-06-07T20:30"
    assert douyin_entry["collection_name"] == "EDC刀光火工具集"
    assert douyin_entry["collection"]["name"] == "EDC刀光火工具集"
    assert douyin_entry["platform_specific_overrides"]["collection_management"]["selected_collection_name"] == "EDC刀光火工具集"
    assert result["creator_profile_id"] == "creator-123"
    assert result["publication_context"]["creator_profile_name"] == "FAS"


def test_upgrade_existing_result_restores_missing_platforms_from_packaging(tmp_path: Path) -> None:
    folder = tmp_path / "case"
    material_dir = folder / "smart-copy"
    meta_dir = material_dir / "_meta"
    copy_dir = material_dir / "_copy"
    meta_dir.mkdir(parents=True)
    copy_dir.mkdir(parents=True)

    existing_result = {
        "platforms": [
            {
                "key": "bilibili",
                "label": "B站",
                "titles": ["旧B站标题"],
                "primary_title": "旧B站标题",
                "body": "旧B站正文",
                "tags": ["旧B站标签"],
                "constraints": {},
                "title_label": "标题",
                "body_label": "简介",
                "tag_label": "标签",
            }
        ],
        "cover_matrix": {},
    }
    packaging = {
        "highlights": {"product": "maxace蜂巢3顶配"},
        "platforms": {
            "bilibili": {
                "titles": ["旧B站标题"],
                "description": "旧B站正文",
                "tags": ["旧B站标签"],
            }
        },
        "platform_scope": {
            "requested_platforms": ["bilibili", "youtube", "x"],
            "covered_platforms": ["bilibili", "youtube", "x"],
            "missing_requested_platforms": [],
        },
        "cover_matrix": {
            "landscape_16_9": {
                "cover_path": "E:/covers/youtube-cover.jpg",
                "cover_size": [1600, 900],
                "members": ["bilibili", "youtube"],
            },
            "landscape_4_3": {
                "cover_path": "E:/covers/x-cover.jpg",
                "cover_size": [1440, 1080],
                "members": ["x"],
            },
        },
    }
    (meta_dir / "smart-copy.json").write_text(json.dumps(existing_result, ensure_ascii=False, indent=2), encoding="utf-8")
    (meta_dir / "platform-packaging.json").write_text(json.dumps(packaging, ensure_ascii=False, indent=2), encoding="utf-8")
    (copy_dir / "01-bilibili-titles.txt").write_text("1. 旧B站标题\n", encoding="utf-8")
    (copy_dir / "01-bilibili-body.txt").write_text("旧B站正文\n", encoding="utf-8")
    (copy_dir / "01-bilibili-tags.txt").write_text("旧B站标签\n", encoding="utf-8")
    (copy_dir / "07-youtube-titles.txt").write_text("1. YouTube新标题\n", encoding="utf-8")
    (copy_dir / "07-youtube-body.txt").write_text("YouTube新正文\n", encoding="utf-8")
    (copy_dir / "07-youtube-tags.txt").write_text("YouTube标签A, YouTube标签B\n", encoding="utf-8")
    (copy_dir / "08-x-body.txt").write_text("X新正文\n", encoding="utf-8")
    (copy_dir / "08-x-tags.txt").write_text("#X标签A\n", encoding="utf-8")

    result = upgrade_existing_intelligent_copy_result(
        str(folder),
        platforms=["bilibili", "youtube", "x"],
    )

    platform_keys = [item["key"] for item in result["platforms"]]
    assert platform_keys == ["bilibili", "youtube", "x"]

    youtube_item = next(item for item in result["platforms"] if item["key"] == "youtube")
    assert youtube_item["primary_title"] == "YouTube新标题"
    assert youtube_item["body"] == "YouTube新正文"
    assert youtube_item["tags"] == ["YouTube标签A", "YouTube标签B"]

    updated_packaging = json.loads((meta_dir / "platform-packaging.json").read_text(encoding="utf-8"))
    assert sorted(updated_packaging["platforms"].keys()) == ["bilibili", "x", "youtube"]
    assert updated_packaging["platform_scope"]["covered_platforms"] == ["bilibili", "x", "youtube"]
