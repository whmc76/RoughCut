from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from roughcut.publication_duplicate_audit import (
    build_duplicate_groups,
    build_duplicate_history_gate_report,
    extract_current_content_signatures,
)
from roughcut.publication import _build_publication_logical_signature_payload


def _attempt(
    *,
    attempt_id: str,
    status: str,
    scheduled_publish_at: str,
    media_path: str,
    browser_profile_id: str,
    dedupe_signature: str = "dup-signature-1",
    run_status: str = "",
    provider_task_id: str = "",
    job_id: str = "job-1",
) -> SimpleNamespace:
    logical_signature = _build_publication_logical_signature_payload(
        platform="douyin",
        content_kind="video",
        media_path=media_path,
        title="两款同时开！美杜莎4顶配次顶配差别出来了",
        body="正文",
        tags=["EDC折刀", "刀具装备"],
    )
    return SimpleNamespace(
        id=attempt_id,
        job_id=job_id,
        status=status,
        run_status=run_status,
        provider_status="",
        provider_task_id=provider_task_id,
        platform="douyin",
        creator_profile_id="creator-1",
        account_label="FAS",
        external_url="",
        error_code="",
        created_at=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 31, 12, 30, tzinfo=timezone.utc),
        request_payload={
            "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
            "body": "正文",
            "tags": ["EDC折刀", "刀具装备"],
            "scheduled_publish_at": scheduled_publish_at,
            "media_items": [{"local_path": media_path}],
            "metadata": {"browser_profile_id": browser_profile_id},
            "publication_dedupe_signature": {"value": dedupe_signature},
            "publication_logical_signature": logical_signature,
        },
    )


def test_build_duplicate_groups_detects_schedule_variants_for_same_media_and_profile() -> None:
    attempts = [
        _attempt(
            attempt_id="attempt-1",
            status="scheduled_pending",
            scheduled_publish_at="2026-05-31T21:00",
            media_path="E:/media/maxace4.mp4",
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
        ),
        _attempt(
            attempt_id="attempt-2",
            status="published",
            scheduled_publish_at="2026-05-31T22:45",
            media_path="E:/media/maxace4.mp4",
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
        ),
    ]

    groups = build_duplicate_groups(
        attempts,
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path="E:/media/maxace4.mp4",
    )

    assert len(groups) == 1
    assert "multiple_successful_publications" in groups[0].reasons
    assert "multiple_schedule_variants_same_live_content" in groups[0].reasons


def test_build_duplicate_groups_filters_out_other_profile_or_media() -> None:
    attempts = [
        _attempt(
            attempt_id="attempt-1",
            status="scheduled_pending",
            scheduled_publish_at="2026-05-31T21:00",
            media_path="E:/media/maxace4.mp4",
            browser_profile_id="browser-profile:chrome:other",
        ),
        _attempt(
            attempt_id="attempt-2",
            status="published",
            scheduled_publish_at="2026-05-31T22:45",
            media_path="E:/media/other.mp4",
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
        ),
    ]

    groups = build_duplicate_groups(
        attempts,
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path="E:/media/maxace4.mp4",
    )

    assert groups == []


def test_extract_current_content_signatures_supports_platform_packaging_shape() -> None:
    signatures = extract_current_content_signatures(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀", "刀具装备"],
            }
        },
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )

    assert len(signatures) == 1
    assert signatures[0]


def test_extract_current_content_signatures_falls_back_to_material_scope_when_target_platforms_missing() -> None:
    signatures = extract_current_content_signatures(
        material_payload={
            "platform_scope": {
                "requested_platforms": ["douyin"],
                "covered_platforms": ["douyin"],
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )

    assert len(signatures) == 1
    assert signatures[0]


def test_extract_current_content_signatures_falls_back_to_material_contract_scope_when_root_scope_missing() -> None:
    signatures = extract_current_content_signatures(
        material_payload={
            "material_contract": {
                "platform_scope": {
                    "requested_platforms": ["douyin"],
                    "covered_platforms": ["douyin"],
                }
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )

    assert len(signatures) == 1
    assert signatures[0]


def test_extract_current_content_signatures_uses_media_path_for_local_media_platforms() -> None:
    first = extract_current_content_signatures(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀", "刀具装备"],
            }
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )
    second = extract_current_content_signatures(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀", "刀具装备"],
            }
        },
        media_path="E:/media/other.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0] != second[0]


def test_build_duplicate_groups_prefers_stored_logical_signature_for_content_signature_matching() -> None:
    media_path = "E:/media/maxace4.mp4"
    signatures = extract_current_content_signatures(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀", "刀具装备"],
            }
        },
        media_path=media_path,
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
    )
    attempt = _attempt(
        attempt_id="attempt-1",
        status="processing",
        scheduled_publish_at="",
        media_path=media_path,
        browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
    )
    attempt.request_payload["title"] = "发生漂移的旧标题"
    attempt.request_payload["body"] = "发生漂移的旧正文"
    attempt.request_payload["tags"] = ["old-tag"]

    groups = build_duplicate_groups(
        [attempt, _attempt(
            attempt_id="attempt-2",
            status="submitted",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
        )],
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path=media_path,
        content_signatures=signatures,
    )

    assert len(groups) == 1
    assert "multiple_active_attempts" in groups[0].reasons


def test_build_duplicate_groups_uses_logical_signature_as_default_group_key_when_dedupe_drifts() -> None:
    media_path = "E:/media/maxace4.mp4"
    attempts = [
        _attempt(
            attempt_id="attempt-1",
            status="processing",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            dedupe_signature="dup-signature-a",
        ),
        _attempt(
            attempt_id="attempt-2",
            status="submitted",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            dedupe_signature="dup-signature-b",
        ),
    ]

    groups = build_duplicate_groups(
        attempts,
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path=media_path,
    )

    assert len(groups) == 1
    assert groups[0].logical_signature
    assert groups[0].group_signature == groups[0].logical_signature
    assert "multiple_active_attempts" in groups[0].reasons


def test_build_duplicate_groups_ignores_same_job_retry_queue_duplicates_without_provider_task() -> None:
    media_path = "E:/media/maxace4.mp4"
    attempts = [
        _attempt(
            attempt_id="attempt-1",
            status="queued",
            run_status="retry_scheduled",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            job_id="job-1",
        ),
        _attempt(
            attempt_id="attempt-2",
            status="queued",
            run_status="retry_scheduled",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            job_id="job-1",
        ),
    ]

    groups = build_duplicate_groups(
        attempts,
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path=media_path,
    )

    assert groups == []


def test_build_duplicate_groups_keeps_multiple_active_attempts_when_provider_task_exists() -> None:
    media_path = "E:/media/maxace4.mp4"
    attempts = [
        _attempt(
            attempt_id="attempt-1",
            status="queued",
            run_status="retry_scheduled",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            job_id="job-1",
        ),
        _attempt(
            attempt_id="attempt-2",
            status="queued",
            run_status="retry_scheduled",
            provider_task_id="provider-2",
            scheduled_publish_at="",
            media_path=media_path,
            browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
            job_id="job-1",
        ),
    ]

    groups = build_duplicate_groups(
        attempts,
        browser_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        platforms=["douyin"],
        media_path=media_path,
    )

    assert len(groups) == 1
    assert "multiple_active_attempts" in groups[0].reasons


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_relaxes_profile_filter_for_platform_packaging_shape() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return {"groups": []}
        return {
            "groups": [
                {
                    "platform": "douyin",
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "reasons": ["multiple_active_attempts"],
                }
            ]
        }

    report = await build_duplicate_history_gate_report(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            }
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        allow_republish=False,
        audit_fn=_fake_audit,
    )

    assert len(calls) == 2
    assert calls[0]["browser_profile_ids"] == ["browser-profile:chrome:21104fd69d72ad7267c2"]
    assert calls[1]["browser_profile_ids"] == []
    assert report["status"] == "failed"
    assert report["profile_filter_relaxed"] is True


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_merges_relaxed_profile_groups_when_primary_is_partial() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return {
                "groups": [
                    {
                        "group_signature": "sig-1",
                        "logical_signature": "sig-1",
                        "dedupe_signature": "dedupe-a",
                        "platform": "douyin",
                        "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                        "reasons": ["multiple_active_attempts"],
                        "total_attempts": 1,
                    }
                ]
            }
        return {
            "groups": [
                {
                    "group_signature": "sig-1",
                    "logical_signature": "sig-1",
                    "dedupe_signature": "dedupe-b",
                    "platform": "douyin",
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "reasons": ["multiple_active_attempts"],
                    "total_attempts": 4,
                }
            ]
        }

    report = await build_duplicate_history_gate_report(
        material_payload={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            }
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        allow_republish=False,
        audit_fn=_fake_audit,
    )

    assert len(calls) == 2
    assert calls[0]["browser_profile_ids"] == ["browser-profile:chrome:21104fd69d72ad7267c2"]
    assert calls[1]["browser_profile_ids"] == []
    assert report["status"] == "failed"
    assert report["profile_filter_relaxed"] is True
    assert report["groups"][0]["total_attempts"] == 4
    assert report["groups"][0]["dedupe_signature"] == "dedupe-b"


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_falls_back_to_material_scope_when_target_platforms_missing() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"groups": []}

    report = await build_duplicate_history_gate_report(
        material_payload={
            "platform_scope": {
                "requested_platforms": ["douyin"],
                "covered_platforms": ["douyin"],
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        allow_republish=False,
        audit_fn=_fake_audit,
    )

    assert calls[0]["platforms"] == ["douyin"]
    assert calls[0]["content_signatures"]
    assert report["status"] == "passed"


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_falls_back_to_material_contract_scope_when_root_scope_missing() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"groups": []}

    report = await build_duplicate_history_gate_report(
        material_payload={
            "material_contract": {
                "platform_scope": {
                    "requested_platforms": ["douyin"],
                    "covered_platforms": ["douyin"],
                }
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=["browser-profile:chrome:21104fd69d72ad7267c2"],
        allow_republish=False,
        audit_fn=_fake_audit,
    )

    assert calls[0]["platforms"] == ["douyin"]
    assert calls[0]["content_signatures"]
    assert report["status"] == "passed"


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_falls_back_to_material_creator_profile_when_browser_profile_missing() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"groups": []}

    report = await build_duplicate_history_gate_report(
        material_payload={
            "creator_profile_id": "creator-1",
            "publication_context": {
                "creator_profile_id": "creator-1",
            },
            "platform_scope": {
                "requested_platforms": ["douyin"],
                "covered_platforms": ["douyin"],
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=[],
        allow_republish=False,
        audit_fn=_fake_audit,
    )

    assert calls[0]["creator_profile_ids"] == ["creator-1"]
    assert calls[0]["browser_profile_ids"] == []
    assert report["status"] == "passed"


@pytest.mark.asyncio
async def test_build_duplicate_history_gate_report_can_disable_material_creator_profile_fallback() -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"groups": []}

    report = await build_duplicate_history_gate_report(
        material_payload={
            "creator_profile_id": "creator-1",
            "publication_context": {
                "creator_profile_id": "creator-1",
            },
            "platform_scope": {
                "requested_platforms": ["douyin"],
                "covered_platforms": ["douyin"],
            },
            "platforms": {
                "douyin": {
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "description": "正文",
                    "tags": ["EDC折刀"],
                }
            },
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=[],
        target_profile_ids=[],
        allow_republish=False,
        allow_material_creator_profile_fallback=False,
        audit_fn=_fake_audit,
    )

    assert calls[0]["creator_profile_ids"] == []
    assert calls[0]["browser_profile_ids"] == []
    assert report["status"] == "passed"
