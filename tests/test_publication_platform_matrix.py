from __future__ import annotations

from roughcut.publication_platform_matrix import (
    platform_allows_field_edits_while_processing,
    platform_cover_project_mode,
    platform_cover_asset_policy,
    platform_draft_resume_policy,
    platform_publish_entry_url,
    platform_publish_projects,
    platform_skips_explicit_tag_entry,
    platform_skips_explicit_visibility_entry,
    platform_stop_when_current_page_already_correct,
    platform_upload_processing_blocks_final_publish_only,
    publication_platform_capabilities,
)


def test_platform_publish_scheme_exposes_entry_url_and_projects() -> None:
    assert platform_publish_entry_url("kuaishou") == "https://cp.kuaishou.com/article/publish/video"
    projects = platform_publish_projects("kuaishou")
    assert projects[0]["key"] == "media_upload"
    assert projects[0]["label"] == "上传视频"
    assert projects[-1]["key"] == "final_publish"


def test_platform_publish_scheme_tracks_prebuilt_cover_policy_and_processing_behavior() -> None:
    assert platform_cover_asset_policy("kuaishou") == "upload_prebuilt_asset_only"
    assert platform_draft_resume_policy("bilibili") == "discard_existing_draft"
    assert platform_allows_field_edits_while_processing("douyin") is True
    assert platform_upload_processing_blocks_final_publish_only("bilibili") is True
    assert platform_stop_when_current_page_already_correct("bilibili") is True


def test_kuaishou_requires_landscape_4_3_primary_cover_slot() -> None:
    capabilities = publication_platform_capabilities("kuaishou")
    slots = capabilities.get("required_cover_slots") or []
    assert slots[0]["slot"] == "landscape_4_3"
    assert slots[0]["matrix_key"] == "landscape_4_3"


def test_bilibili_requires_dual_cover_slots_with_4_3_primary() -> None:
    capabilities = publication_platform_capabilities("bilibili")
    slots = capabilities.get("required_cover_slots") or []
    assert [item["slot"] for item in slots] == ["landscape_4_3", "landscape_16_9"]
    assert slots[0]["matrix_key"] == "landscape_4_3"
    assert slots[0]["target_size"] == {"width": 1440, "height": 1080}
    assert slots[1]["matrix_key"] == "landscape_16_9"
    assert slots[1]["target_size"] == {"width": 1600, "height": 900}


def test_kuaishou_skips_explicit_tag_and_visibility_projects() -> None:
    projects = [item["key"] for item in platform_publish_projects("kuaishou")]
    assert "tags" not in projects
    assert "visibility" not in projects
    assert platform_skips_explicit_tag_entry("kuaishou") is True
    assert platform_skips_explicit_visibility_entry("kuaishou") is True


def test_kuaishou_mainline_publish_scheme_only_uses_main_cover_path_and_stops_when_page_is_already_correct() -> None:
    assert platform_cover_project_mode("kuaishou") == "main_cover_only"
    assert platform_stop_when_current_page_already_correct("kuaishou") is True
    assert platform_upload_processing_blocks_final_publish_only("kuaishou") is True
