from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_publication_real_release_gate as release_gate


def test_build_field_differences_normalizes_scheduled_publish_timezone() -> None:
    differences = release_gate._build_field_differences(
        {"scheduled_publish_at": "2026-06-02T06:20:00+08:00"},
        {"scheduled_publish_at": "2026-06-01T22:20:00+00:00"},
    )

    assert differences == []


def test_load_platform_packaging_payload_resolves_sibling_from_material_json(tmp_path: Path):
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text("{}", encoding="utf-8")
    platform_packaging = tmp_path / "platform-packaging.json"
    platform_packaging.write_text(
        json.dumps(
            {
                "platform_scope": {
                    "requested_platforms": ["douyin"],
                    "covered_platforms": ["douyin"],
                },
                "platforms": {
                    "douyin": {
                        "title": "真实标题",
                        "description": "真实正文",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    packaging, scope, failures = release_gate._load_platform_packaging_payload(
        "",
        str(material_json),
    )

    assert failures == []
    assert packaging["douyin"]["title"] == "真实标题"
    assert scope["covered_platforms"] == ["douyin"]


def test_load_platform_packaging_payload_prefers_explicit_path_over_material_json_sibling(tmp_path: Path):
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text("{}", encoding="utf-8")
    sibling_packaging = tmp_path / "platform-packaging.json"
    sibling_packaging.write_text(
        json.dumps({"platforms": {"douyin": {"title": "SIBLING TITLE"}}}),
        encoding="utf-8",
    )
    explicit_packaging = tmp_path / "explicit-platform-packaging.json"
    explicit_packaging.write_text(
        json.dumps({"platforms": {"douyin": {"title": "EXPLICIT TITLE"}}}),
        encoding="utf-8",
    )

    packaging, scope, failures = release_gate._load_platform_packaging_payload(
        str(explicit_packaging),
        str(material_json),
    )

    assert failures == []
    assert scope == {}
    assert packaging["douyin"]["title"] == "EXPLICIT TITLE"


@pytest.mark.asyncio
async def test_collect_prepublish_draft_candidates_accepts_receipt_audit_payload_without_run_result() -> None:
    class _FakeRowsResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _FakeSession:
        async def execute(self, _statement):
            return _FakeRowsResult(
                [
                    (
                        "douyin",
                        "needs_human",
                        None,
                        {
                            "title": "标题",
                            "body": "",
                        },
                        {
                            "result": {
                                "material_integrity": {
                                    "platform": "douyin",
                                    "verification_reason": "receipt_bound",
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "douyin_content_manage_receipt",
                                        "receipt_target_bound": True,
                                    },
                                },
                                "publication_audit": {
                                    "verified": False,
                                    "required_unverified": ["cover"],
                                    "required_reupload": [],
                                },
                            },
                            "error": {
                                "code": "publication_audit_unverified",
                                "message": "cover 未通过",
                            },
                        },
                        "publication_audit_unverified",
                        "browser_agent",
                        "",
                        "",
                        "needs_human",
                        "verified",
                    )
                ]
            )

    result = await release_gate._collect_prepublish_draft_candidates(
        session=_FakeSession(),
        media_path="E:/materials/maxace/output.mp4",
        platforms=["douyin"],
    )

    assert "douyin" in result
    assert result["douyin"]["platform"] == "douyin"
    assert "terminal_status:publication_audit_unverified" in result["douyin"]["reasons"]


def test_build_platform_packaging_recomputes_root_publish_ready_from_platform_entries() -> None:
    packaging = release_gate._build_platform_packaging(
        ["douyin", "youtube"],
        media_path="E:/materials/maxace/output.mp4",
        platform_packaging={
            "douyin": {
                "titles": ["抖音标题"],
                "description": "抖音简介",
                "live_publish_preflight": {"status": "ready"},
                "blocking_reasons": [],
                "publish_ready": True,
            },
            "youtube": {
                "titles": ["YouTube 标题"],
                "description": "YouTube 简介",
                "live_publish_preflight": {
                    "status": "blocked",
                    "missing_required_surfaces": ["editor_surface"],
                },
                "blocking_reasons": ["youtube 缺少 live_publish_preflight"],
                "publish_ready": False,
            },
        },
    )

    assert packaging["publish_ready"] is False
    assert packaging["platforms"]["douyin"]["publish_ready"] is True
    assert packaging["platforms"]["youtube"]["publish_ready"] is False
    assert packaging["platforms"]["youtube"]["blocking_reasons"] == [
        "youtube 缺少 live_publish_preflight"
    ]


def test_build_platform_packaging_allows_fresh_draft_prepare_without_publish_ready() -> None:
    packaging = release_gate._build_platform_packaging(
        ["douyin"],
        media_path="E:/materials/maxace/output.mp4",
        platform_packaging={
            "douyin": {
                "titles": ["抖音标题"],
                "description": "抖音简介",
                "blocking_reasons": ["缺少合集策略"],
                "publish_ready": False,
            }
        },
        allow_prepare_without_publish_ready=True,
    )

    assert packaging["publish_ready"] is True
    assert packaging["platforms"]["douyin"]["publish_ready"] is True
    assert packaging["platforms"]["douyin"]["reported_publish_ready"] is False
    assert packaging["platforms"]["douyin"]["reported_blocking_reasons"] == ["缺少合集策略"]
    assert packaging["platforms"]["douyin"]["platform_specific_overrides"]["allow_prepare_without_publish_ready"] is True


def test_is_fresh_draft_prepare_mode_requires_draft_status_and_visibility() -> None:
    assert release_gate._is_fresh_draft_prepare_mode({"draft_created"}, "draft") is True
    assert release_gate._is_fresh_draft_prepare_mode({"draft_created", "processing"}, "draft") is True
    assert release_gate._is_fresh_draft_prepare_mode({"draft_created"}, "public") is False
    assert release_gate._is_fresh_draft_prepare_mode({"published"}, "draft") is False


def test_browser_agent_ready_target_platforms_skips_creator_probe_for_fresh_draft_prepare() -> None:
    assert (
        release_gate._browser_agent_ready_target_platforms(
            effective_platforms=["youtube", "douyin"],
            fresh_draft_prepare_mode=True,
        )
        == []
    )
    assert (
        release_gate._browser_agent_ready_target_platforms(
            effective_platforms=["youtube", "douyin"],
            fresh_draft_prepare_mode=False,
        )
        == ["youtube", "douyin"]
    )


def test_single_attempt_execution_mode_enabled_for_fresh_draft_prepare() -> None:
    assert release_gate._use_single_attempt_execution_mode(fresh_draft_prepare_mode=True) is True
    assert release_gate._use_single_attempt_execution_mode(fresh_draft_prepare_mode=False) is False


def test_should_reinvoke_publication_worker_allows_only_first_tick_in_single_attempt_mode() -> None:
    assert release_gate._should_reinvoke_publication_worker(
        single_attempt_execution_mode=True,
        worker_invocation_count=0,
    ) is True
    assert release_gate._should_reinvoke_publication_worker(
        single_attempt_execution_mode=True,
        worker_invocation_count=1,
    ) is False
    assert release_gate._should_reinvoke_publication_worker(
        single_attempt_execution_mode=False,
        worker_invocation_count=99,
    ) is True


def test_should_attempt_recovery_submission_disabled_in_single_attempt_mode() -> None:
    assert release_gate._should_attempt_recovery_submission(single_attempt_execution_mode=True) is False
    assert release_gate._should_attempt_recovery_submission(single_attempt_execution_mode=False) is True


def test_validate_authoritative_publication_browser_runtime_rejects_non_chrome_or_non_bridge() -> None:
    failures = release_gate._validate_authoritative_publication_browser_runtime(
        {
            "health": {
                "attached_profile_binding": {"browser": "edge", "profile_id": ""},
                "browser_transport": {"transport": "legacy_cdp_http"},
            }
        }
    )

    assert any("Google Chrome" in item for item in failures)
    assert any("chrome_extension_bridge" in item for item in failures)
    assert any("profile_id" in item for item in failures)


def test_build_fresh_draft_prepare_live_check_uses_healthz_authority_only() -> None:
    live_check = release_gate._build_fresh_draft_prepare_live_check(
        {
            "health": {
                "cdp_status": "ok",
                "browser_transport": {"transport": "chrome_extension_bridge"},
                "attached_profile_binding": {
                    "browser": "chrome",
                    "profile_id": "browser-profile:chrome:demo-profile-a",
                },
            }
        }
    )

    assert live_check["cdp"]["connected"] is True
    assert live_check["cdp"]["source"] == "browser_agent_healthz"
    assert live_check["platform_checks"] == {}


def test_build_fresh_draft_prepare_live_check_accepts_degraded_bridge_state() -> None:
    live_check = release_gate._build_fresh_draft_prepare_live_check(
        {
            "health": {
                "cdp_status": "degraded",
                "browser_transport": {"transport": "chrome_extension_bridge", "bridge_client_id": "bridge-test-client"},
                "attached_profile_binding": {
                    "browser": "chrome",
                    "profile_id": "browser-profile:chrome:demo-profile-a",
                },
            }
        }
    )

    assert live_check["cdp"]["connected"] is True
    assert live_check["cdp"]["state"] == "degraded"


def test_build_platform_options_routes_fresh_draft_prepare_directly_to_platform_executor() -> None:
    options = release_gate._build_platform_options(
        ["douyin"],
        visibility_mode="draft",
        platform_packaging={
            "douyin": {
                "description": "正文",
                "tags": ["tag-a"],
                "publish_ready": False,
            }
        },
        fresh_draft_prepare_mode=True,
    )

    overrides = options["douyin"]["platform_specific_overrides"]
    assert overrides["prepare_only_current_page"] is False
    assert overrides["stop_before_final_publish"] is False
    assert overrides["fresh_start_platform_tab"] is True
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is False
    assert overrides["verification_only_current_page"] is False
    assert overrides["prepublish_only_current_page"] is False
    assert overrides["verify_media_upload"] is False
    assert overrides["wait_for_publish_confirmation"] is False


def test_build_platform_options_fresh_draft_prepare_does_not_require_scheme_seed_options() -> None:
    options = release_gate._build_platform_options(
        ["douyin"],
        visibility_mode="draft",
        platform_packaging={
            "douyin": {
                "description": "正文",
                "tags": ["tag-a"],
                "publish_ready": False,
            }
        },
        seed_platform_options={
            "douyin": {
                "native_topics": ["#添加话题"],
                "ui_control_semantics": {"collection_select": True},
                "platform_specific_overrides": {"decision_policy": "only_choose_from_browser_agent_inventory"},
            }
        },
        fresh_draft_prepare_mode=True,
    )

    overrides = options["douyin"]["platform_specific_overrides"]
    assert overrides["prepare_only_current_page"] is False
    assert overrides["stop_before_final_publish"] is False
    assert overrides["fresh_start_platform_tab"] is True
    assert options["douyin"].get("native_topics") == ["#添加话题"]
    assert options["douyin"].get("ui_control_semantics") == {"collection_select": True}


def test_build_platform_options_fresh_draft_prepare_ignores_recovery_hint_overrides() -> None:
    options = release_gate._build_platform_options(
        ["douyin"],
        visibility_mode="draft",
        platform_packaging={
            "douyin": {
                "description": "正文",
                "tags": ["tag-a"],
                "publish_ready": False,
            }
        },
        platform_recovery_hints={
            "douyin": {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
                "repair_only_current_page": True,
                "verification_only_current_page": True,
            }
        },
        fresh_draft_prepare_mode=True,
    )

    overrides = options["douyin"]["platform_specific_overrides"]
    assert overrides["prepare_only_current_page"] is False
    assert overrides["stop_before_final_publish"] is False
    assert overrides["fresh_start_platform_tab"] is True
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is False
    assert overrides["repair_only_current_page"] is False
    assert overrides["verification_only_current_page"] is False


def test_fresh_draft_prepare_does_not_require_existing_platform_tabs() -> None:
    live_check = {
        "cdp": {
            "connected": True,
            "platform_checks": {
                "douyin": {"status": "needs_open_publish_page"},
            },
        }
    }
    failures: list[str] = []
    require_tabs = True
    fresh_draft_prepare_mode = True
    if require_tabs and not fresh_draft_prepare_mode:
        platform_checks = live_check.get("cdp", {}).get("platform_checks") or {}
        missing = [platform for platform, item in platform_checks.items() if (item or {}).get("status") != "found"]
        if missing:
            failures.append(f"缺少目标平台发布页标签: {', '.join(missing)}")

    assert failures == []


def test_coerce_platform_packaging_entry_derives_blocking_reasons_from_preflight_when_missing() -> None:
    entry = release_gate._coerce_platform_packaging_entry(
        "douyin",
        {
            "titles": ["真实标题"],
            "description": "真实正文",
            "publish_ready": True,
            "blocking_reasons": [],
            "live_publish_preflight": {
                "status": "blocked",
                "missing_required_surfaces": ["cover"],
            },
        },
        fallback_title="fallback",
        fallback_description="fallback body",
    )

    assert entry["publish_ready"] is False
    assert entry["blocking_reasons"] == ["缺少发布前必要页面能力：cover"]


def test_publish_receipt_pending_summary_requires_matching_signature():
    summary = {
        "status": "submitted",
        "strict_contract_reasons": [
            "status_in_progress",
            "content_plan_fill_gaps_pending",
            "submitted_response_payload_empty_snapshot",
        ],
        "expected_signature": "sig-1",
        "actual_signature": "sig-1",
        "signature_match": True,
        "request_payload_plan_match": True,
        "duplicate_detected": False,
    }

    assert release_gate._is_publish_receipt_pending_summary(summary) is True


def test_publish_receipt_pending_summary_rejects_missing_or_mismatched_signature():
    missing_signature_summary = {
        "status": "submitted",
        "strict_contract_reasons": ["status_in_progress", "submitted_response_payload_empty_snapshot"],
        "expected_signature": "sig-1",
        "actual_signature": "",
        "signature_match": False,
        "request_payload_plan_match": True,
    }
    mismatched_signature_summary = {
        "status": "submitted",
        "strict_contract_reasons": ["status_in_progress", "content_plan_fill_gaps_pending"],
        "expected_signature": "sig-1",
        "actual_signature": "sig-2",
        "signature_match": False,
        "request_payload_plan_match": True,
    }

    assert release_gate._is_publish_receipt_pending_summary(missing_signature_summary) is False
    assert release_gate._is_publish_receipt_pending_summary(mismatched_signature_summary) is False


def test_publish_receipt_pending_summary_allows_missing_actual_signature_when_plan_match_and_snapshot_missing():
    summary = {
        "status": "submitted",
        "strict_contract_reasons": [
            "submitted_content_plan_fill_gaps_pending",
            "submitted_response_payload_unverified",
        ],
        "expected_signature": "sig-1",
        "actual_signature": "",
        "signature_match": True,
        "request_payload_plan_match": True,
        "request_fields_snapshot_missing": True,
        "request_fields_snapshot_trusted": False,
        "duplicate_detected": False,
    }

    assert release_gate._is_publish_receipt_pending_summary(summary) is True


def test_receipt_pending_recommendation_avoids_default_clear_draft():
    summary = {
        "status": "submitted",
        "strict_contract_reasons": [
            "status_in_progress",
            "content_plan_fill_gaps_pending",
            "submitted_response_payload_empty_snapshot",
        ],
        "expected_signature": "sig-1",
        "actual_signature": "sig-1",
        "signature_match": True,
        "request_payload_plan_match": True,
        "request_fields_snapshot_missing": False,
        "request_fields_snapshot_trusted": True,
        "actual_request_fields_snapshot_source": "response_payload",
        "duplicate_detected": False,
        "request_contract_ready": True,
    }

    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        summary,
        is_stable=True,
    )

    pending = next(item for item in recommendations if item["issue"] == "publish_receipt_pending")
    assert "clear_draft_context" not in pending["operations"]
    assert "force_publish_page_refresh" in pending["operations"]
    assert pending["auto_remediable"] is False


def test_receipt_pending_suppresses_snapshot_derived_clear_draft_recommendations():
    summary = {
        "status": "submitted",
        "strict_contract_reasons": [
            "response_payload_unverified",
            "submitted_content_plan_fill_gaps_pending",
            "submitted_response_payload_empty_snapshot",
        ],
        "expected_signature": "sig-1",
        "actual_signature": "sig-1",
        "signature_match": True,
        "signature_fields_match": False,
        "signature_fields_available": False,
        "expected_signature_fields": {"title": "x"},
        "request_payload_plan_match": True,
        "request_fields_snapshot_missing": False,
        "request_fields_snapshot_trusted": False,
        "actual_request_fields_snapshot_source": "response_payload",
        "request_contract_ready": True,
        "request_plan_fill_gaps": [{"field": "title", "expected": "x", "actual": ""}],
        "field_mismatches": [{"field": "title", "expected": "x", "actual": ""}],
        "duplicate_detected": False,
    }

    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        summary,
        is_stable=True,
    )

    issues = {item["issue"] for item in recommendations}
    assert "publish_receipt_pending" in issues
    assert "status_in_progress" in issues
    assert "submitted_content_plan_fill_gaps_pending" not in issues
    assert "submitted_response_payload_empty_snapshot" not in issues
    assert "signature_fields_missing" not in issues
    assert "content_plan_fill_gaps" not in issues
    assert "content_fields_mismatch" not in issues


def test_post_repair_structural_blocker_recommendation_keeps_refresh_only():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        {
            "status": "needs_human",
            "post_repair_preserve_context": True,
            "publication_audit": {
                "required_unverified": ["upload_ready"],
            },
        },
        is_stable=True,
    )

    item = next(entry for entry in recommendations if entry["issue"] == "post_repair_structural_blocker")
    assert "force_publish_page_refresh" in item["operations"]
    assert "clear_draft_context" not in item["operations"]
    assert "verify_media_upload" in item["operations"]
    assert item["auto_remediable"] is False


def test_receipt_target_unbound_recommendation_keeps_refresh_only():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        {
            "status": "needs_human",
            "receipt_target_unbound": True,
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": False,
                "receipt_binding_source": "unbound_manage_receipt",
            },
        },
        is_stable=True,
    )

    item = next(entry for entry in recommendations if entry["issue"] == "receipt_target_unbound")
    assert "force_publish_page_refresh" in item["operations"]
    assert "wait_for_publish_confirmation" in item["operations"]
    assert "clear_draft_context" not in item["operations"]
    assert item["auto_remediable"] is False


def test_receipt_target_unbound_recommendation_suppresses_manage_page_field_noise():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        {
            "status": "needs_human",
            "receipt_target_unbound": True,
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": False,
                "receipt_binding_source": "unbound_manage_receipt",
                "post_publish_surface": "douyin_content_manage_receipt",
            },
            "request_contract_ready": True,
            "request_fields_snapshot_missing": True,
            "actual_request_fields_snapshot_source": "request_payload",
            "request_plan_fill_gaps": [{"field": "declaration"}],
            "request_payload_field_mismatches": [{"field": "copy_material"}],
            "field_mismatches": [{"field": "declaration"}],
            "strict_contract_reasons": ["terminal_status:needs_human"],
        },
        is_stable=True,
    )

    issues = {entry["issue"] for entry in recommendations}
    assert "receipt_target_unbound" in issues
    assert "publication_request_fields_snapshot_missing" not in issues
    assert "publication_request_field_snapshot_untrusted" not in issues
    assert "content_plan_fill_gaps" not in issues
    assert "publication_request_payload_fields_mismatch" not in issues
    assert "content_fields_mismatch" not in issues


def test_pre_publish_upload_pending_recommendation_keeps_wait_only():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "douyin",
        {
            "status": "processing",
            "error_code": "douyin_pre_publish_upload_pending",
            "pre_publish_upload_pending": True,
            "publication_audit": {
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
            },
        },
        is_stable=False,
    )

    item = next(entry for entry in recommendations if entry["issue"] == "pre_publish_upload_pending")
    assert "force_publish_page_refresh" in item["operations"]
    assert "verify_media_upload" in item["operations"]
    assert "wait_for_publish_confirmation" in item["operations"]
    assert "clear_draft_context" not in item["operations"]
    assert item["auto_remediable"] is False


def test_upload_not_applied_recommendation_keeps_wait_only():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "kuaishou",
        {
            "status": "needs_human",
            "error_code": "kuaishou_media_upload_failed",
            "upload_not_applied": True,
            "upload_failure_reason": "upload_not_applied",
            "verification_reason": "upload_failed",
        },
        is_stable=False,
    )

    item = next(entry for entry in recommendations if entry["issue"] == "upload_not_applied")
    assert "force_publish_page_refresh" in item["operations"]
    assert "verify_media_upload" in item["operations"]
    assert "wait_for_publish_confirmation" in item["operations"]
    assert "clear_draft_context" not in item["operations"]
    assert item["auto_remediable"] is False


def test_route_auth_required_recommendation_never_requests_clear_draft():
    recommendations = release_gate._build_platform_recovery_recommendations(
        "wechat-channels",
        {
            "status": "needs_human",
            "error_code": "wechat-channels_route_auth_required",
            "route_auth_required": True,
            "verification_reason": "auth_required",
        },
        is_stable=False,
    )

    item = next(entry for entry in recommendations if entry["issue"] == "route_auth_required")
    assert item["operations"] == []
    assert item["auto_remediable"] is False


def test_prepublish_clear_draft_decision_keeps_submitted_pending_clean():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="submitted",
        reasons=[
            "response_payload_unverified",
            "submitted_content_plan_fill_gaps_pending",
            "submitted_response_payload_empty_snapshot",
            "plan_fill_gaps",
            "plan_fields_mismatch",
        ],
        publish_receipt_pending=True,
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_terminal_draft_clear_failed_does_not_force_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=["terminal_status:draft_clear_failed"],
        publish_receipt_pending=False,
        error_code="draft_clear_failed",
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_terminal_snapshot_gaps_do_not_force_clear_draft_after_draft_clear_failed():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=[
            "terminal_status:draft_clear_failed",
            "plan_fill_gaps",
            "plan_fields_mismatch",
            "response_payload_unverified",
        ],
        publish_receipt_pending=False,
        error_code="draft_clear_failed",
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_response_payload_terminal_content_plan_mismatch_only_forces_refresh():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=[
            "content_plan_fill_gaps_pending",
            "plan_fields_mismatch",
            "plan_fill_gaps",
            "terminal_status:douyin_pre_publish_content_plan_mismatch",
        ],
        publish_receipt_pending=False,
        error_code="douyin_pre_publish_content_plan_mismatch",
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_request_payload_processing_snapshot_never_forces_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="processing",
        reasons=[
            "active_status_stale",
            "plan_fields_mismatch",
            "status_in_progress",
        ],
        publish_receipt_pending=True,
        snapshot_source="request_payload",
    )

    assert should_clear is False


def test_prepublish_response_payload_queued_gap_snapshot_does_not_force_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="queued",
        reasons=[
            "content_plan_fill_gaps_pending",
            "plan_fields_mismatch",
            "plan_fill_gaps",
            "status_in_progress",
        ],
        publish_receipt_pending=False,
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_response_payload_queued_stale_gap_snapshot_only_forces_refresh():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="queued",
        reasons=[
            "active_status_stale",
            "content_plan_fill_gaps_pending",
            "plan_fields_mismatch",
            "plan_fill_gaps",
            "status_in_progress",
        ],
        publish_receipt_pending=False,
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_response_payload_processing_stale_gap_snapshot_only_forces_refresh():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="processing",
        reasons=[
            "active_status_stale",
            "content_plan_fill_gaps_pending",
            "plan_fields_mismatch",
            "plan_fill_gaps",
            "status_in_progress",
        ],
        publish_receipt_pending=False,
        snapshot_source="response_payload",
    )

    assert should_clear is False


def test_prepublish_post_repair_structural_blocker_never_forces_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=[
            "terminal_status:douyin_verification_only_material_integrity_failed",
            "status_in_progress",
        ],
        publish_receipt_pending=False,
        error_code="douyin_verification_only_material_integrity_failed",
        snapshot_source="response_payload",
        post_repair_preserve_context=True,
    )

    assert should_clear is False


def test_prepublish_route_auth_required_never_forces_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=["terminal_status:needs_human"],
        publish_receipt_pending=False,
        error_code="wechat-channels_route_auth_required",
        snapshot_source="response_payload",
        route_auth_required=True,
    )

    assert should_clear is False


def test_prepublish_unbound_receipt_never_forces_clear_draft():
    should_clear = release_gate._should_clear_draft_from_prepublish_reasons(
        status="needs_human",
        reasons=[
            "terminal_status:douyin_final_publish_unconfirmed",
            "submitted_response_payload_unverified",
        ],
        publish_receipt_pending=False,
        error_code="douyin_final_publish_unconfirmed",
        snapshot_source="response_payload",
        receipt_target_unbound=True,
    )

    assert should_clear is False


def test_adaptive_recovery_overrides_keep_route_auth_required_login_only():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "wechat-channels",
        attempt_count=4,
        summary={
            "status": "needs_human",
            "error_code": "wechat-channels_route_auth_required",
            "route_auth_required": True,
            "verification_reason": "auth_required",
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is False
    assert overrides["verify_media_upload"] is False
    assert overrides["wait_for_publish_confirmation"] is False


def test_build_publication_verification_payload_accepts_processing_for_fresh_draft_prepare() -> None:
    status, failures, summaries, recommendations = release_gate._build_publication_verification_payload(
        [
            {
                "platform": "douyin",
                "status": "processing",
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_payload": {
                    "platform": "douyin",
                    "adapter": "browser_agent",
                    "title": "抖音标题",
                    "body": "抖音正文",
                },
                "response_payload": {},
                "result": {},
                "error_code": "",
            }
        ],
        expected_platforms=["douyin"],
        expected_statuses={"draft_created"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {
                    "platform": "douyin",
                    "adapter": "browser_agent",
                    "title": "抖音标题",
                    "body": "抖音正文",
                },
            }
        },
        fresh_draft_prepare_mode=True,
    )

    assert status == "passed"
    assert failures == []
    assert summaries[0]["strict_contract_verified"] is True
    assert recommendations == []


def test_adaptive_recovery_overrides_keep_pre_publish_upload_pending_wait_only():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "douyin",
        attempt_count=3,
        summary={
            "status": "processing",
            "error_code": "douyin_pre_publish_upload_pending",
            "pre_publish_upload_pending": True,
            "publication_audit": {
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
            },
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert reasons


def test_adaptive_recovery_overrides_keep_upload_not_applied_wait_only():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "kuaishou",
        attempt_count=2,
        summary={
            "status": "needs_human",
            "error_code": "kuaishou_media_upload_failed",
            "upload_not_applied": True,
            "upload_failure_reason": "upload_not_applied",
            "verification_reason": "upload_failed",
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert reasons


def test_runtime_context_in_progress_only_forces_refresh():
    flags = release_gate._runtime_context_recovery_flags(["in_progress:submitted"])

    assert flags == {
        "clear_draft_context": False,
        "force_publish_page_refresh": True,
    }


def test_task_envelope_without_result_does_not_fake_field_snapshot():
    payload = {
        "task": {
            "task_id": "task-1",
            "id": "task-1",
            "platform": "douyin",
            "status": "queued",
            "result": {},
        }
    }

    assert release_gate._extract_publication_field_snapshot(payload) == {}


def test_task_progress_snapshot_is_used_when_result_snapshot_missing():
    payload = {
        "task": {
            "task_id": "task-progress-1",
            "status": "processing",
            "result": {},
            "progress": {
                "phase": "publish_receipt_poll",
                "publication_field_snapshot": {
                    "platform": "douyin",
                    "title": "进度标题",
                    "visibility_or_publish_mode": "scheduled",
                },
                "publication_audit": {
                    "checklist": {
                        "title": {"actual": "进度标题", "verified": True},
                    }
                },
            },
        }
    }

    assert release_gate._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "visibility_or_publish_mode": "scheduled",
    }
    audit, issues = release_gate._extract_publication_audit(payload)
    assert issues == []
    assert audit["checklist"]["title"]["actual"] == "进度标题"


def test_timeout_progress_snapshot_and_audit_are_used_when_result_is_sparse():
    payload = {
        "task": {
            "task_id": "task-timeout-1",
            "status": "submitted",
            "result": {
                "timeout_progress": {
                    "publication_field_snapshot": {
                        "platform": "douyin",
                        "title": "超时进度标题",
                    },
                    "publication_audit": {
                        "checklist": {
                            "title": {"actual": "超时进度标题", "verified": True},
                        }
                    },
                },
            },
        }
    }

    assert release_gate._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "超时进度标题",
    }
    audit, issues = release_gate._extract_publication_audit(payload)
    assert issues == []
    assert audit["checklist"]["title"]["actual"] == "超时进度标题"


def test_task_progress_material_integrity_fields_are_promoted_to_snapshot_and_audit():
    payload = {
        "task": {
            "task_id": "task-material-1",
            "status": "processing",
            "progress": {
                "phase": "dispatch_platform_adapter",
                "material_integrity": {
                    "platform": "douyin",
                    "verified": False,
                    "failures": ["schedule", "upload_ready"],
                    "fields": {
                        "title": {"actual": "进度标题", "verified": True},
                        "body": {"actual": "进度正文", "verified": True},
                        "tags": {"actual": ["标签A", "标签B"], "verified": True},
                        "schedule": {"actual": "2026-05-31 20:30", "verified": True},
                    },
                },
            },
        }
    }

    assert release_gate._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "body": "进度正文",
        "hashtags": ["标签A", "标签B"],
        "display_hashtags": ["#标签A", "#标签B"],
        "structured_tags": ["标签A", "标签B"],
        "scheduled_publish_at": "2026-05-31T20:30",
    }
    audit, issues = release_gate._extract_publication_audit(payload)
    assert audit["checklist"]["title"]["actual"] == "进度标题"
    assert audit["required_unverified"] == ["schedule", "upload_ready"]
    assert issues == ["schedule", "upload_ready"]


def test_task_progress_material_integrity_snapshot_wins_over_sparse_top_level_fields():
    payload = {
        "fields": {
            "title": "进度标题",
            "body": "进度正文",
            "hashtags": ["标签A", "标签B"],
        },
        "task": {
            "task_id": "task-material-priority-1",
            "status": "processing",
            "progress": {
                "phase": "dispatch_platform_adapter",
                "material_integrity": {
                    "platform": "douyin",
                    "verified": True,
                    "failures": [],
                    "fields": {
                        "title": {"actual": "进度标题", "verified": True},
                        "body": {"actual": "进度正文", "verified": True},
                        "tags": {"actual": ["标签A", "标签B"], "verified": True},
                        "schedule": {"actual": "2026-05-31 20:30", "verified": True},
                    },
                },
            },
        },
    }

    assert release_gate._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "body": "进度正文",
        "hashtags": ["标签A", "标签B"],
        "display_hashtags": ["#标签A", "#标签B"],
        "structured_tags": ["标签A", "标签B"],
        "scheduled_publish_at": "2026-05-31T20:30",
    }


def test_evaluate_progress_does_not_use_request_payload_snapshot_while_submitted():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "",
        "declaration": None,
        "content_kind": "video",
        "hashtags": [],
        "display_hashtags": [],
        "structured_tags": [],
        "native_topics": [],
        "category": None,
        "collection": None,
        "cover_path": None,
        "copy_material": {},
        "visibility_or_publish_mode": None,
        "scheduled_publish_at": None,
        "ui_control_semantics": {
            "schedule_publish": False,
            "collection_select": False,
        },
        "platform_specific_overrides": {},
        "media_urls": [],
        "media_items_count": 0,
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    status, failures, summaries, terminal_failure, _, _ = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "submitted",
                "run_status": "submitted",
                "provider_status": "queued",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "queued",
                        "result": {},
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {
                    key: value
                    for key, value in request_payload.items()
                    if key != "publication_plan_signature"
                },
            }
        },
    )

    summary = summaries[0]
    assert summary["request_fields_snapshot_missing"] is True
    assert summary["actual_request_fields_snapshot_source"] == ""
    assert summary["request_payload_plan_match"] is True


def test_evaluate_progress_backfills_non_echoed_fields_from_request_when_material_integrity_exists():
    cover_slots = [
        {
            "slot": "feed_primary",
            "cover_path": "E:/cover.jpg",
            "target_size": {"width": 1080, "height": 1920},
        }
    ]
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "declaration": None,
        "content_kind": "video",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "native_topics": [],
        "category": None,
        "collection": None,
        "cover_path": "E:/cover.jpg",
        "cover_slots": cover_slots,
        "copy_material": {"body": "正文", "cover_slots": cover_slots},
        "visibility_or_publish_mode": None,
        "scheduled_publish_at": None,
        "ui_control_semantics": {
            "schedule_publish": False,
            "collection_select": False,
        },
        "platform_specific_overrides": {},
        "media_urls": ["E:/video.mp4"],
        "media_items": [
            {
                "kind": "video",
                "local_path": "E:/video.mp4",
            }
        ],
        "media_items_count": 1,
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    status, failures, summaries, terminal_failure, _, _ = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "processing",
                "run_status": "processing",
                "provider_status": "processing",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "processing",
                        "progress": {
                            "material_integrity": {
                                "platform": "douyin",
                                "verified": False,
                                "failures": ["upload_ready"],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                },
                            }
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {
                    key: value
                    for key, value in request_payload.items()
                    if key != "publication_plan_signature"
                },
            }
        },
    )

    summary = summaries[0]
    assert summary["request_fields_snapshot_missing"] is False
    assert summary["actual_request_fields_snapshot_source"] == "response_payload"
    assert summary["request_fields_snapshot_trusted"] is True
    assert summary["actual_request_fields"]["cover_path"] == "E:/cover.jpg"
    assert summary["actual_request_fields"]["cover_slots"] == cover_slots
    assert summary["actual_request_fields"]["media_urls"] == ["E:/video.mp4"]
    assert summary["actual_request_fields"]["media_items_count"] == 1
    assert summary["actual_request_fields"]["title"] == "hello"
    assert summary["material_integrity_pending"] is True
    assert "submitted_response_payload_unverified" not in summary["strict_contract_reasons"]
    assert "request_fields_snapshot_missing" not in summary["strict_contract_reasons"]
    assert "content_plan_fill_gaps_pending" not in summary["strict_contract_reasons"]


def test_upload_progress_pending_signal_detects_visible_upload_telemetry():
    payload = {
        "task": {
            "status": "processing",
            "progress": {
                "actions": [
                    {
                        "kind": "douyin_upload_ready_wait",
                        "ready": False,
                        "last": {
                            "busy": True,
                            "ready": False,
                        },
                    }
                ]
            },
        }
    }

    assert release_gate._has_upload_progress_pending_signal(payload) is True


def test_evaluate_progress_keeps_submitted_pending_out_of_recoverable_platforms():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "",
        "declaration": None,
        "content_kind": "video",
        "hashtags": [],
        "display_hashtags": [],
        "structured_tags": [],
        "native_topics": [],
        "category": None,
        "collection": None,
        "cover_path": None,
        "copy_material": {},
        "visibility_or_publish_mode": None,
        "scheduled_publish_at": None,
        "ui_control_semantics": {
            "schedule_publish": False,
            "collection_select": False,
        },
        "platform_specific_overrides": {},
        "media_urls": [],
        "media_items_count": 0,
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "submitted",
                "run_status": "submitted",
                "provider_status": "queued",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "queued",
                        "result": {},
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {
                    key: value
                    for key, value in request_payload.items()
                    if key != "publication_plan_signature"
                },
            }
        },
    )

    assert status == "running"
    assert terminal_failure is False
    assert recoverable_platforms == []
    assert recoverable_failures == []


def test_expected_platform_manifest_preserves_packaging_publication_metadata():
    manifest = release_gate._build_expected_platform_manifest(
        ["xiaohongshu"],
        title="源标题",
        description="源简介",
        media_path="E:/media/output.mp4",
        platform_packaging={
            "xiaohongshu": {
                "titles": ["平台标题"],
                "description": "平台简介",
                "tags": ["tag1"],
                "cover_path": "E:/covers/xhs.jpg",
                "cover_slots": [
                    {
                        "slot": "feed_primary",
                        "cover_path": "E:/covers/xhs.jpg",
                        "target_size": {"width": 1080, "height": 1440},
                    }
                ],
                "declaration": "原创声明",
                "visibility_or_publish_mode": "scheduled",
                "scheduled_publish_at": "2026-05-31T21:00",
                "collection_name": "EDC潮玩桌搭",
                "platform_specific_overrides": {
                    "selected_declarations": ["原创声明"],
                },
                "copy_material": {
                    "source": "intelligent_copy_material_self_heal",
                },
            }
        },
    )

    entry = manifest["xiaohongshu"]
    assert entry["visibility_or_publish_mode"] == "scheduled"
    assert entry["request_fields"]["cover_path"] == "E:/covers/xhs.jpg"
    assert entry["request_fields"]["cover_slots"] == [
        {
            "slot": "feed_primary",
            "cover_path": "E:/covers/xhs.jpg",
            "target_size": {"width": 1080, "height": 1440},
        }
    ]
    assert entry["request_fields"]["declaration"] == "原创声明"
    assert entry["request_fields"]["scheduled_publish_at"] == "2026-05-31T21:00"
    assert entry["request_fields"]["collection"] == {"name": "EDC潮玩桌搭"}
    assert entry["request_fields"]["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]
    assert entry["request_fields"]["copy_material"]["source"] == "intelligent_copy_material_self_heal"


def test_expected_platform_manifest_applies_effective_platform_options():
    manifest = release_gate._build_expected_platform_manifest(
        ["youtube"],
        title="源标题",
        description="源简介",
        media_path="E:/media/output.mp4",
        platform_packaging={
            "youtube": {
                "titles": ["平台标题"],
                "description": "平台简介",
                "tags": ["tag1"],
            }
        },
        effective_platform_options={
            "youtube": {
                "visibility_or_publish_mode": "schedule",
                "scheduled_publish_at": "2026-06-04T21:00:00+08:00",
                "platform_specific_overrides": {
                    "collection_policy": "skip",
                    "skip_collection_select": True,
                },
            }
        },
    )

    entry = manifest["youtube"]
    assert entry["visibility_or_publish_mode"] == "schedule"
    assert entry["request_fields"]["visibility_or_publish_mode"] == "schedule"
    assert entry["request_fields"]["scheduled_publish_at"] == "2026-06-04T21:00:00+08:00"
    assert entry["request_fields"]["ui_control_semantics"] == {
        "schedule_publish": True,
        "collection_select": False,
    }
    assert entry["request_fields"]["platform_specific_overrides"]["collection_policy"] == "skip"
    assert entry["request_fields"]["platform_specific_overrides"]["skip_collection_select"] is True


def test_expected_platform_manifest_drops_youtube_placeholder_category():
    manifest = release_gate._build_expected_platform_manifest(
        ["youtube"],
        title="源标题",
        description="源简介",
        media_path="E:/media/output.mp4",
        platform_packaging={
            "youtube": {
                "titles": ["平台标题"],
                "description": "平台简介",
                "tags": ["tag1"],
                "category": "视频",
            }
        },
    )

    assert manifest["youtube"]["request_fields"]["category"] is None


def test_expected_platform_manifest_drops_youtube_placeholder_category_from_effective_options():
    manifest = release_gate._build_expected_platform_manifest(
        ["youtube"],
        title="源标题",
        description="源简介",
        media_path="E:/media/output.mp4",
        platform_packaging={
            "youtube": {
                "titles": ["平台标题"],
                "description": "平台简介",
                "tags": ["tag1"],
            }
        },
        effective_platform_options={
            "youtube": {
                "category": "视频",
            }
        },
    )

    assert manifest["youtube"]["request_fields"]["category"] is None


def test_plan_contract_request_fields_preserve_nested_platform_overrides():
    actual = release_gate._coerce_plan_contract_request_fields(
        {
            "platform": "xiaohongshu",
            "platform_specific_overrides": {
                "selected_declarations": ["原创声明"],
                "topic_selection_plan": {
                    "mode": "prefer_platform_topic_suggestions_then_fallback_to_tag_input",
                },
            },
        },
        "E:/media/output.mp4",
    )

    assert actual["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]
    assert actual["platform_specific_overrides"]["topic_selection_plan"]["mode"] == "prefer_platform_topic_suggestions_then_fallback_to_tag_input"


def test_expected_request_fields_derive_native_topics_and_collection_semantics_from_overrides():
    actual = release_gate._build_expected_request_fields(
        platform="douyin",
        platform_title="标题",
        body="正文",
        tags=["EDC", "跳刀"],
        scheduled_publish_at="2026-06-07T20:30",
        collection=None,
        platform_specific_overrides={
            "topic_selection_plan": {
                "requested_topics": ["MAXACE", "美杜莎4", "开箱"],
            },
            "collection_management": {
                "status": "needs_create",
                "target_collection_name": "EDC刀光火工具集",
            },
        },
        media_path="E:/media/output.mp4",
        adapter="browser_agent",
    )

    assert actual["native_topics"] == ["MAXACE", "美杜莎4", "开箱"]
    assert actual["ui_control_semantics"] == {
        "schedule_publish": True,
        "collection_select": True,
    }


def test_enrich_plan_contract_expected_fields_recomputes_collection_and_topics_semantics():
    enriched = release_gate._enrich_plan_contract_expected_fields(
        {
            "native_topics": [],
            "collection": None,
            "ui_control_semantics": {
                "schedule_publish": True,
                "collection_select": False,
            },
            "platform_specific_overrides": {
                "topic_selection_plan": {
                    "requested_topics": ["EDC", "开箱"],
                },
                "collection_management": {
                    "target_collection_name": "EDC刀光火工具集",
                },
            },
        },
        {
            "native_topics": ["EDC", "开箱"],
            "collection": {"name": "EDC刀光火工具集"},
            "ui_control_semantics": {
                "schedule_publish": True,
                "collection_select": True,
            },
        },
    )

    assert enriched["native_topics"] == ["EDC", "开箱"]
    assert enriched["collection"] == {"name": "EDC刀光火工具集"}
    assert enriched["ui_control_semantics"]["collection_select"] is True


def test_plan_contract_request_fields_ignore_execution_only_republish_overrides():
    actual = release_gate._coerce_plan_contract_request_fields(
        {
            "platform": "douyin",
            "platform_specific_overrides": {
                "verification_only_current_page": True,
                "recovery_mode": "receipt_rebind",
                "force_republish": True,
                "allow_duplicate_publication": True,
            },
        },
        "E:/media/output.mp4",
    )

    assert actual["platform_specific_overrides"]["verification_only_current_page"] is True
    assert actual["platform_specific_overrides"]["recovery_mode"] == "receipt_rebind"
    assert "force_republish" not in actual["platform_specific_overrides"]
    assert "allow_duplicate_publication" not in actual["platform_specific_overrides"]


def test_build_platform_options_preserves_blocked_live_publish_preflight():
    options = release_gate._build_platform_options(
        ["xiaohongshu"],
        platform_packaging={
            "xiaohongshu": {
                "scheduled_publish_at": "2026-05-31T20:30",
                "platform_specific_overrides": {
                    "live_publish_preflight": {
                        "policy": "block_final_publish_when_required_surface_missing",
                        "status": "blocked",
                        "summary": "缺少定时发布面",
                        "missing_required_surfaces": ["schedule"],
                    },
                },
            }
        },
    )

    assert options["xiaohongshu"]["live_publish_preflight"]["status"] == "blocked"
    assert options["xiaohongshu"]["live_publish_preflight"]["missing_required_surfaces"] == ["schedule"]


def test_coerce_platform_packaging_entry_uses_shared_default_declaration_for_bilibili():
    entry = release_gate._coerce_platform_packaging_entry(
        "bilibili",
        {"title": "B站标题", "description": "B站简介"},
        fallback_title="源标题",
        fallback_description="源简介",
    )

    assert entry["declaration"] == "内容无需标注"


def test_coerce_platform_packaging_entry_derives_publish_ready_from_blocked_preflight_when_flag_missing():
    entry = release_gate._coerce_platform_packaging_entry(
        "douyin",
        {
            "titles": ["标题"],
            "description": "简介",
            "tags": ["tag"],
            "blocking_reasons": ["封面缺失"],
            "live_publish_preflight": {
                "status": "blocked",
                "missing_required_surfaces": ["cover"],
            },
        },
        fallback_title="fallback",
        fallback_description="fallback body",
    )

    assert entry["publish_ready"] is False


def test_build_platform_options_does_not_force_ignore_publish_ready_gate_for_refresh_only_recovery():
    options = release_gate._build_platform_options(
        ["douyin"],
        platform_packaging={
            "douyin": {
                "platform_specific_overrides": {
                    "live_publish_preflight": {
                        "status": "ready",
                        "missing_required_surfaces": [],
                    },
                },
            }
        },
        force_refresh_platforms={"douyin"},
    )

    overrides = options["douyin"]["platform_specific_overrides"]
    assert overrides["force_publish_page_refresh"] is True
    assert "ignore_publish_ready_gate" not in overrides


def test_build_platform_options_propagates_allow_republish_into_platform_overrides():
    options = release_gate._build_platform_options(
        ["douyin"],
        platform_packaging={
            "douyin": {
                "platform_specific_overrides": {
                    "live_publish_preflight": {
                        "status": "ready",
                        "missing_required_surfaces": [],
                    },
                },
            }
        },
        allow_republish=True,
    )

    overrides = options["douyin"]["platform_specific_overrides"]
    assert overrides["force_republish"] is True
    assert overrides["allow_duplicate_publication"] is True


def test_coerce_platform_packaging_entry_uses_fallback_title_when_titles_missing():
    entry = release_gate._coerce_platform_packaging_entry(
        "kuaishou",
        {
            "description": "正文",
            "tags": ["EDC"],
        },
        fallback_title="MAXACE 美杜莎4 顶配次顶配开箱",
        fallback_description="兜底正文",
    )

    assert entry["titles"] == ["MAXACE 美杜莎4 顶配次顶配开箱"]


def test_coerce_platform_packaging_entry_defaults_youtube_visibility_to_public():
    entry = release_gate._coerce_platform_packaging_entry(
        "youtube",
        {
            "description": "正文",
            "tags": ["EDC"],
        },
        fallback_title="MAXACE 美杜莎4 顶配次顶配开箱",
        fallback_description="兜底正文",
    )

    assert entry["visibility_or_publish_mode"] == "public"


def test_build_platform_packaging_omits_absent_metadata_fields_from_ready_entry():
    packaging = release_gate._build_platform_packaging(
        ["kuaishou"],
        media_path="E:/media/maxace4.mp4",
        platform_packaging={
            "kuaishou": {
                "description": "正文",
                "tags": ["EDC折刀", "开箱"],
                "cover_path": "cover.jpg",
                "platform_specific_overrides": {
                    "collection_policy": "skip",
                    "skip_collection_select": True,
                    "stop_before_final_publish": True,
                },
                "publish_ready": True,
            }
        },
    )

    entry = packaging["platforms"]["kuaishou"]
    assert packaging["publish_ready"] is True
    assert entry["publish_ready"] is True
    assert entry["titles"] == ["maxace4"]
    assert "category" not in entry
    assert "collection" not in entry
    assert "declaration" not in entry
    assert "visibility_or_publish_mode" not in entry
    assert "scheduled_publish_at" not in entry


def test_adaptive_recovery_overrides_keep_submitted_pending_wait_only():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "douyin",
        attempt_count=3,
        summary={
            "status": "submitted",
            "strict_contract_reasons": [
                "status_in_progress",
                "content_plan_fill_gaps_pending",
                "submitted_response_payload_empty_snapshot",
            ],
            "expected_signature": "sig-1",
            "actual_signature": "sig-1",
            "signature_match": True,
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert reasons


def test_adaptive_recovery_overrides_keep_timeout_terminal_wait_only_without_trusted_snapshot():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "xiaohongshu",
        attempt_count=4,
        summary={
            "status": "needs_human",
            "error_code": "publication_task_timeout",
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
            "strict_contract_reasons": ["terminal_status:needs_human"],
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert reasons


def test_adaptive_recovery_overrides_keep_unbound_receipt_wait_only():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "douyin",
        attempt_count=4,
        summary={
            "status": "published",
            "error_code": "douyin_final_publish_unconfirmed",
            "receipt_target_unbound": True,
            "strict_contract_reasons": ["receipt_target_unbound"],
        },
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert any("保留现场" in item or "回执" in item for item in reasons)


def test_sanitize_recovery_overrides_blocks_history_clear_draft_for_submitted_pending():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": True,
            "wait_for_publish_confirmation": True,
        },
        summary={
            "status": "submitted",
            "strict_contract_reasons": [
                "status_in_progress",
                "content_plan_fill_gaps_pending",
                "submitted_response_payload_empty_snapshot",
            ],
            "expected_signature": "sig-1",
            "actual_signature": "sig-1",
            "signature_match": True,
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert reasons


def test_sanitize_recovery_overrides_blocks_history_clear_draft_for_pending_terminal_timeout():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": True,
        },
        summary={
            "status": "needs_human",
            "error_code": "publication_task_timeout",
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
            "strict_contract_reasons": ["terminal_status:needs_human"],
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert reasons


def test_sanitize_recovery_overrides_preserves_post_repair_context_without_clear_draft():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": False,
        },
        summary={
            "status": "needs_human",
            "error_code": "douyin_verification_only_material_integrity_failed",
            "post_repair_preserve_context": True,
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["recovery_mode"] == "auto_recover"
    assert any("预发布已完成字段级修复且仅剩结构性 blocker" in item for item in reasons)


def test_sanitize_recovery_overrides_preserves_upload_not_applied_without_clear_draft():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": False,
        },
        summary={
            "status": "needs_human",
            "error_code": "kuaishou_media_upload_failed",
            "upload_not_applied": True,
            "upload_failure_reason": "upload_not_applied",
            "verification_reason": "upload_failed",
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "auto_recover"
    assert any("页面未真正接住媒体" in item for item in reasons)


def test_sanitize_recovery_overrides_preserves_unbound_receipt_without_clear_draft():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": False,
            "verification_only_current_page": True,
        },
        summary={
            "status": "needs_human",
            "error_code": "douyin_final_publish_unconfirmed",
            "receipt_target_unbound": True,
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["recovery_mode"] == "auto_recover"
    assert any("发布后回执尚未唯一绑定到本次作品" in item for item in reasons)


def test_adaptive_recovery_overrides_promotes_publish_receipt_pending_to_safe_receipt_rebind():
    overrides, reasons = release_gate._adaptive_recovery_overrides(
        "toutiao",
        attempt_count=2,
        summary={
            "status": "submitted",
            "strict_contract_reasons": [
                "submitted_content_plan_fill_gaps_pending",
                "submitted_response_payload_unverified",
            ],
            "expected_signature": "sig-1",
            "actual_signature": "sig-1",
            "signature_match": True,
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
            "duplicate_detected": False,
        },
        default_trigger="auto_recover",
    )

    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["capture_response_timeout_ms"] >= 90000
    assert reasons


def test_sanitize_recovery_overrides_promotes_publish_receipt_pending_to_safe_receipt_rebind():
    overrides, reasons = release_gate._sanitize_recovery_overrides_for_summary(
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": False,
        },
        summary={
            "status": "submitted",
            "strict_contract_reasons": [
                "submitted_content_plan_fill_gaps_pending",
                "submitted_response_payload_unverified",
            ],
            "expected_signature": "sig-1",
            "actual_signature": "sig-1",
            "signature_match": True,
            "request_payload_plan_match": True,
            "request_fields_snapshot_missing": True,
            "request_fields_snapshot_trusted": False,
            "duplicate_detected": False,
        },
        default_recovery_mode="auto_recover",
    )

    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert any("receipt_rebind" in item for item in reasons)


def test_extract_discovery_recovery_overrides_preserves_safe_rebind_flags():
    overrides, actions, retryable, target = release_gate._extract_discovery_recovery_overrides(
        {
            "retryable": True,
            "next_steps": ["保留现场继续核对回执"],
            "recovery_plan": {
                "recovery_overrides": {
                    "recovery_mode": "receipt_rebind",
                    "force_publish_page_refresh": True,
                    "verification_only_current_page": True,
                    "wait_for_publish_confirmation": True,
                    "verify_media_upload": True,
                }
            },
        },
        summary={
            "status": "needs_human",
            "error_code": "douyin_final_publish_unconfirmed",
            "receipt_target_unbound": True,
        },
    )

    assert retryable is True
    assert "保留现场继续核对回执" in actions
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["force_publish_page_refresh"] is True
    assert target["target_adapter"] == "browser_agent"
    assert target["target_execution_mode"] == "browser_agent"


def test_merge_recovery_target_platform_overrides_preserves_explicit_receipt_rebind_mode():
    merged = release_gate._merge_recovery_target_platform_overrides(
        {
            "recovery_mode": "receipt_rebind",
            "verification_only_current_page": True,
            "force_publish_page_refresh": True,
            "clear_draft_context": False,
        },
        {
            "recovery_mode": "douyin_verification_only_material_integrity_failed",
            "clear_draft_context": True,
        },
        {
            "cover_policy": "platform_default",
            "skip_cover_upload": True,
        },
    )

    assert merged["recovery_mode"] == "receipt_rebind"
    assert merged["verification_only_current_page"] is True
    assert merged["clear_draft_context"] is False
    assert merged["force_publish_page_refresh"] is True
    assert merged["cover_policy"] == "platform_default"
    assert merged["skip_cover_upload"] is True


def test_summarize_recovery_knowledge_base_preserves_safe_rebind_flags():
    summary = release_gate._summarize_recovery_knowledge_base(
        {
            "version": 1,
            "platforms": {
                "douyin": {
                    "sig-1": {
                        "signature": "sig-1",
                        "count": 2,
                        "last_seen": "2026-06-01T00:00:00+08:00",
                        "error_code": "douyin_final_publish_unconfirmed",
                        "verify_media_upload": True,
                        "wait_for_publish_confirmation": True,
                        "verification_only_current_page": True,
                        "prepare_only_current_page": False,
                    }
                }
            },
            "prepublish_platforms": {
                "douyin": {
                    "sig-2": {
                        "signature": "sig-2",
                        "count": 1,
                        "last_seen": "2026-06-01T00:00:00+08:00",
                        "error_code": "douyin_pre_publish_upload_pending",
                        "verify_media_upload": True,
                        "wait_for_publish_confirmation": True,
                        "prepare_only_current_page": True,
                    }
                }
            },
        }
    )

    top_entry = summary["top_entries"]["douyin"][0]
    assert top_entry["verification_only_current_page"] is True
    assert top_entry["prepare_only_current_page"] is False
    prepublish_entry = summary["prepublish_top_entries"]["douyin"][0]
    assert prepublish_entry["prepare_only_current_page"] is True
    assert prepublish_entry["verification_only_current_page"] is False


def test_evaluate_progress_does_not_auto_recover_needs_human_without_known_retry_code():
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "xiaohongshu",
                "status": "needs_human",
                "run_status": "needs_human",
                "provider_status": "needs_human",
                "error_code": "draft_clear_failed",
                "adapter": "browser_agent",
                "request_payload": {
                    "publication_plan_signature": {
                        "value": "sig-1",
                        "fields": {"title": "hello"},
                    }
                },
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "needs_human",
                        "error": {
                            "code": "draft_clear_failed",
                            "message": "draft clear failed",
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["xiaohongshu"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "xiaohongshu": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {"title": "hello"},
            }
        },
    )

    assert recoverable_platforms == []
    assert terminal_failure is True
    assert failures
    assert summaries[0]["status"] == "needs_human"


def test_evaluate_progress_marks_unbound_receipt_as_terminal_without_clear_draft_recovery():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "published",
                "run_status": "published",
                "provider_status": "published",
                "adapter": "browser_agent",
                "external_url": "https://www.douyin.com/video/123",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "published",
                        "result": {
                            "material_integrity": {
                                "platform": "douyin",
                                "verified": False,
                                "failures": ["receipt"],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": False,
                                    "receipt_binding_source": "unbound_manage_receipt",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": False,
                                "required_unverified": ["receipt"],
                                "issues": ["receipt target missing"],
                                "summary": {"status": "error"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": False,
                                    "receipt_binding_source": "unbound_manage_receipt",
                                },
                            },
                            "final_publish": {
                                "receipt_like": True,
                                "post_click_integrity": {
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "douyin_content_manage_receipt",
                                        "receipt_target_bound": False,
                                        "receipt_binding_source": "unbound_manage_receipt",
                                    }
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "failed"
    assert terminal_failure is True
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert failures
    assert summaries[0]["receipt_target_unbound"] is True
    assert "receipt_target_unbound" in summaries[0]["strict_contract_reasons"]


def test_evaluate_progress_accepts_bound_manage_receipt_as_verified_success():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "scheduled_publish_at": "2026-05-31T20:30",
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "published",
                "run_status": "published",
                "provider_status": "published",
                "adapter": "browser_agent",
                "external_url": "https://www.douyin.com/video/123",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "published",
                        "result": {
                            "material_integrity": {
                                "platform": "douyin",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "schedule": {"actual": "2026-05-31 20:30", "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                            "final_publish": {
                                "receipt_like": True,
                                "post_click_integrity": {
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "douyin_content_manage_receipt",
                                        "receipt_target_bound": True,
                                        "receipt_binding_source": "douyin_manage_card",
                                    }
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_target_unbound"] is False
    assert str(summaries[0]["receipt_binding_id"]).startswith("receipt-binding:")
    assert summaries[0]["strict_contract_verified"] is True
    assert summaries[0]["publication_audit"]["verified"] is True


def test_evaluate_progress_accepts_bound_xiaohongshu_publish_success_receipt_as_verified_success():
    request_payload = {
        "platform": "xiaohongshu",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-xhs-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "xiaohongshu",
                "status": "published",
                "run_status": "published",
                "provider_status": "published",
                "adapter": "browser_agent",
                "external_url": "https://www.xiaohongshu.com/explore/abc",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-xhs-1",
                        "status": "published",
                        "result": {
                            "material_integrity": {
                                "platform": "xiaohongshu",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "cover": {"actual": "01-xiaohongshu-cover.jpg", "verified": True},
                                    "collection": {"actual": "EDC潮玩桌搭", "verified": True},
                                    "declaration": {"actual": "原创声明", "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "xiaohongshu_publish_success_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "xiaohongshu_publish_success",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "xiaohongshu_publish_success_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "xiaohongshu_publish_success",
                                },
                            },
                            "final_publish": {
                                "receipt_like": True,
                                "post_click_integrity": {
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "xiaohongshu_publish_success_receipt",
                                        "receipt_target_bound": True,
                                        "receipt_binding_source": "xiaohongshu_publish_success",
                                    }
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["xiaohongshu"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "xiaohongshu": {
                "adapter": "browser_agent",
                "content_signature": "sig-xhs-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_target_unbound"] is False
    assert summaries[0]["strict_contract_verified"] is True
    assert summaries[0]["publication_audit"]["verified"] is True


def test_evaluate_progress_accepts_bound_xiaohongshu_note_manager_receipt_as_verified_success():
    request_payload = {
        "platform": "xiaohongshu",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-xhs-note-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "xiaohongshu",
                "status": "verified",
                "run_status": "verified",
                "provider_status": "verified",
                "adapter": "browser_agent",
                "external_url": "https://www.xiaohongshu.com/explore/abc",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-xhs-note-1",
                        "status": "verified",
                        "result": {
                            "material_integrity": {
                                "platform": "xiaohongshu",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "cover": {"actual": "01-xiaohongshu-cover.jpg", "verified": True},
                                    "collection": {"actual": "EDC潮玩桌搭", "verified": True},
                                    "declaration": {"actual": "原创声明", "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "xiaohongshu_note_manager_card",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "xiaohongshu_note_manager_card",
                                },
                            },
                            "final_publish": {
                                "receipt_like": True,
                                "post_click_integrity": {
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "xiaohongshu_note_manager_receipt",
                                        "receipt_target_bound": True,
                                        "receipt_binding_source": "xiaohongshu_note_manager_card",
                                    }
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["xiaohongshu"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "xiaohongshu": {
                "adapter": "browser_agent",
                "content_signature": "sig-xhs-note-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_target_unbound"] is False
    assert summaries[0]["strict_contract_verified"] is True
    assert summaries[0]["publication_audit"]["verified"] is True


def test_evaluate_progress_accepts_bound_toutiao_manage_receipt_as_verified_success():
    request_payload = {
        "platform": "toutiao",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-tt-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "toutiao",
                "status": "verified",
                "run_status": "verified",
                "provider_status": "verified",
                "adapter": "browser_agent",
                "external_url": "https://www.toutiao.com/article/abc",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-tt-1",
                        "status": "verified",
                        "result": {
                            "material_integrity": {
                                "platform": "toutiao",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "cover": {"actual": "01-toutiao-cover.jpg", "verified": True},
                                    "collection": {"actual": "", "verified": True},
                                    "declaration": {"actual": "", "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "toutiao_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "toutiao_manage_card",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "toutiao_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "toutiao_manage_card",
                                },
                            },
                            "final_publish": {
                                "receipt_like": True,
                                "post_click_integrity": {
                                    "platform_extras": {
                                        "receipt_like": True,
                                        "post_publish_surface": "toutiao_content_manage_receipt",
                                        "receipt_target_bound": True,
                                        "receipt_binding_source": "toutiao_manage_card",
                                    }
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["toutiao"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "toutiao": {
                "adapter": "browser_agent",
                "content_signature": "sig-tt-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_target_unbound"] is False
    assert summaries[0]["strict_contract_verified"] is True
    assert summaries[0]["publication_audit"]["verified"] is True


def test_evaluate_progress_marks_pre_publish_upload_pending_summary():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "processing",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "status": "processing",
                        "progress": {
                            "publication_field_snapshot": expected_request_fields,
                            "publication_audit": {
                                "verified": False,
                                "required_unverified": ["upload_ready"],
                                "required_reupload": ["upload_ready"],
                            },
                            "material_integrity": {
                                "verified": False,
                                "failures": ["upload_ready"],
                                "fields": {
                                    "upload_ready": {"actual": "waiting", "verified": False},
                                },
                            },
                        },
                        "result": {
                            "error": {"code": "douyin_pre_publish_upload_pending"},
                        },
                    },
                    "error_code": "douyin_pre_publish_upload_pending",
                },
                "error_code": "douyin_pre_publish_upload_pending",
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "running"
    assert terminal_failure is False
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["pre_publish_upload_pending"] is True


def test_evaluate_progress_accepts_verified_stop_before_final_publish_as_draft_created_success():
    request_payload = {
        "platform": "youtube",
        "adapter": "browser_agent",
        "title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手",
        "body": "正文",
        "hashtags": ["MAXACE", "美杜莎4", "开箱对比"],
        "display_hashtags": ["#MAXACE", "#美杜莎4", "#开箱对比"],
        "structured_tags": ["MAXACE", "美杜莎4", "开箱对比"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-yt-stop-1",
            "fields": {"title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "youtube",
                "status": "draft_created",
                "run_status": "draft_created",
                "provider_status": "verified",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-yt-stop-1",
                        "status": "verified",
                        "result": {
                            "material_integrity": {
                                "platform": "youtube",
                                "verified": False,
                                "failures": ["tags"],
                                "verification_reason": "ready",
                                "fields": {
                                    "title": {"actual": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["MAXACE"], "verified": False},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                                "body": "",
                                "hashtags": [],
                                "media_items_count": 0,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "optional_missing": ["tags"],
                            },
                            "final_publish": {
                                "stop_before_final_publish": True,
                                "prepare_only_current_page": True,
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["youtube"],
        expected_statuses={"draft_created"},
        expected_platform_manifest={
            "youtube": {
                "adapter": "browser_agent",
                "content_signature": "sig-yt-stop-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["strict_contract_verified"] is True
    assert summaries[0]["verified_stop_before_final_publish"] is True


def test_evaluate_progress_exposes_explicit_receipt_binding_id_when_present():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "publication_plan_signature": {
            "value": "sig-receipt-1",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "published",
                "run_status": "published",
                "provider_status": "published",
                "adapter": "browser_agent",
                "external_url": "https://www.douyin.com/video/123",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-receipt-1",
                        "status": "published",
                        "result": {
                            "receipt_id": "receipt-explicit-123",
                            "material_integrity": {
                                "platform": "douyin",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-receipt-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_binding_id"] == "receipt-explicit-123"


def test_request_plan_fill_gaps_suppresses_non_required_audit_fields():
    gaps = release_gate._suppress_request_plan_fill_gaps_with_non_required_audit_fields(
        [
            {"field": "declaration", "expected": "无需添加自主声明", "actual": None},
            {"field": "title", "expected": "hello", "actual": None},
        ],
        {
            "checklist": {
                "declaration": {"required": False, "verified": False},
                "title": {"required": True, "verified": False},
            }
        },
    )
    assert gaps == [{"field": "title", "expected": "hello", "actual": None}]


def test_request_field_mismatches_suppress_non_required_audit_fields():
    mismatches = release_gate._suppress_request_field_mismatches_with_non_required_audit_fields(
        [
            {"field": "declaration", "expected": "无需添加自主声明", "actual": None},
            {"field": "title", "expected": "hello", "actual": ""},
        ],
        {
            "checklist": {
                "declaration": {"required": False, "verified": False},
                "title": {"required": True, "verified": False},
            }
        },
    )
    assert mismatches == [{"field": "title", "expected": "hello", "actual": ""}]


def test_should_require_public_url_for_strict_success_skips_bound_receipt_success():
    assert release_gate._should_require_public_url_for_strict_success(
        platform="douyin",
        status="published",
        bound_receipt_verification_success=True,
        is_x_link_share=False,
    ) is False
    assert release_gate._should_require_public_url_for_strict_success(
        platform="douyin",
        status="published",
        bound_receipt_verification_success=False,
        is_x_link_share=False,
    ) is True


def test_serialize_verification_platform_summary_preserves_receipt_and_duplicate_evidence():
    summary = release_gate._serialize_verification_platform_summary(
        {
            "platform": "douyin",
            "attempt_id": "attempt-1",
            "status": "published",
            "signature_match_status": "matched",
            "expected_signature": "sig-1",
            "response_signature": "sig-1",
            "signature_match": True,
            "field_match": True,
            "request_fields_snapshot_trusted": True,
            "field_mismatches": [],
            "request_payload_field_mismatches": [],
            "request_payload_fields_match": True,
            "request_payload_plan_match": True,
            "request_snapshot_plan_match": True,
            "request_field_verification": [],
            "request_payload_field_mismatch_count": 0,
            "request_field_mismatch_count": 0,
            "request_plan_fill_gaps": [],
            "request_contract_ready": True,
            "request_payload_field_mismatch_fields": [],
            "request_field_mismatch_fields": [],
            "strict_contract_reasons": [],
            "request_fields_plan_fill_audit": [],
            "requested_fields": {"title": "hello"},
            "actual_fields": {"title": "hello"},
            "actual_request_fields_snapshot_source": "response_payload",
            "request_payload_fields": {"title": "hello"},
            "strict_contract_verified": True,
            "public_url": "https://www.douyin.com/video/123",
            "error_code": "",
            "duplicate_detected": False,
            "receipt_binding_id": "receipt-binding:abc123",
            "receipt_target_unbound": False,
            "verified_stop_before_final_publish": False,
            "visual_evidence": {
                "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-receipt.png",
                "capture_type": "screenshot",
                "phase": "receipt_rebind",
            },
            "runs_count": 2,
        }
    )

    assert summary["receipt_binding_id"] == "receipt-binding:abc123"
    assert summary["receipt_target_unbound"] is False
    assert summary["verified_stop_before_final_publish"] is False
    assert summary["duplicate_detected"] is False
    assert summary["contract_verified"] is True
    assert summary["visual_evidence"]["artifact_path"].endswith("douyin-receipt.png")
    assert summary["visual_evidence"]["capture_type"] == "screenshot"


def test_build_publication_failure_context_preserves_visual_evidence() -> None:
    context = release_gate._build_publication_failure_context(
        {
            "platform": "douyin",
            "status": "needs_human",
            "expected_signature_fields": {},
            "actual_request_fields": {"title": "demo"},
            "expected_request_fields": {"title": "demo"},
            "request_payload_field_mismatch_fields": [],
            "request_field_mismatch_fields": [],
            "request_plan_fill_gaps": [],
            "strict_contract_reasons": ["content_plan_fill_gaps"],
            "visual_evidence": {
                "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-prepublish.png",
                "capture_type": "screenshot",
                "phase": "pre_publish_page_snapshot",
            },
        }
    )

    assert context["visual_evidence"]["artifact_path"].endswith("douyin-prepublish.png")
    assert context["visual_evidence"]["capture_type"] == "screenshot"
    assert context["visual_evidence"]["phase"] == "pre_publish_page_snapshot"


def test_evaluate_progress_accepts_bound_douyin_receipt_without_public_url_or_non_required_declaration_snapshot():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
        "declaration": "无需添加自主声明",
        "publication_plan_signature": {
            "value": "sig-receipt-2",
            "fields": {"title": "hello"},
        },
        "publication_content_signature": {
            "value": "sig-receipt-2",
            "fields": {"title": "hello"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    snapshot_fields = {
        **expected_request_fields,
        "declaration": "",
    }
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "published",
                "run_status": "published",
                "provider_status": "verified",
                "adapter": "browser_agent",
                "external_url": "",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-receipt-2",
                        "status": "verified",
                        "result": {
                            "publication_plan_signature": "sig-receipt-2",
                            "publication_content_signature": "sig-receipt-2",
                            "material_integrity": {
                                "platform": "douyin",
                                "verified": True,
                                "failures": [],
                                "fields": {
                                    "title": {"actual": "hello", "verified": True},
                                    "body": {"actual": "作品管理里的正文摘要", "verified": False, "required": False},
                                    "tags": {"actual": ["tag-a"], "verified": True},
                                    "declaration": {"actual": "", "verified": False, "required": False},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                            "receipt_id": "receipt-binding:bound-2",
                            "publication_field_snapshot": snapshot_fields,
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "checklist": {
                                    "declaration": {"required": False, "verified": False},
                                    "body": {"required": False, "verified": False},
                                    "receipt": {"required": True, "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "post_publish_surface": "douyin_content_manage_receipt",
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "douyin_manage_card",
                                },
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "browser_agent",
                "content_signature": "sig-receipt-2",
                "signature_fields": {"title": "hello"},
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["receipt_binding_id"] == "receipt-binding:bound-2"
    assert "public_url_missing" not in (summaries[0]["strict_contract_reasons"] or [])
    assert "content_plan_fill_gaps_deferred" not in (summaries[0]["strict_contract_reasons"] or [])


def test_evaluate_progress_accepts_youtube_scheduled_receipt_with_deferred_snapshot_gaps():
    request_payload = {
        "platform": "youtube",
        "adapter": "browser_agent",
        "title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手",
        "body": "正文",
        "hashtags": ["MAXACE", "美杜莎4", "开箱对比"],
        "display_hashtags": ["#MAXACE", "#美杜莎4", "#开箱对比"],
        "structured_tags": ["MAXACE", "美杜莎4", "开箱对比"],
        "content_kind": "video",
        "scheduled_publish_at": "2026-06-01T21:00:00+08:00",
        "publication_plan_signature": {
            "value": "sig-yt-scheduled-1",
            "fields": {"title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手"},
        },
        "publication_content_signature": {
            "value": "sig-yt-scheduled-1",
            "fields": {"title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手"},
        },
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "youtube",
                "status": "scheduled_pending",
                "run_status": "scheduled_pending",
                "provider_status": "scheduled_pending",
                "adapter": "browser_agent",
                "external_url": "https://youtu.be/T-44KNDKkSQ",
                "scheduled_at": "2026-06-01T21:00:00+08:00",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "status": "scheduled_pending",
                        "result": {
                            "material_integrity": {
                                "platform": "youtube",
                                "verified": False,
                                "failures": ["tags"],
                                "verification_reason": "ready",
                                "fields": {
                                    "title": {"actual": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手", "verified": True},
                                    "body": {"actual": "正文", "verified": True},
                                    "tags": {"actual": ["MAXACE"], "verified": False},
                                    "upload_ready": {"actual": "ready", "verified": True},
                                    "schedule": {"actual": "2026-06-01 21:00", "verified": True},
                                },
                                "platform_extras": {
                                    "receipt_like": True,
                                    "receipt_target_bound": True,
                                    "receipt_binding_source": "youtube_studio_editor_link",
                                    "post_publish_surface": "youtube_studio_editor_receipt",
                                    "youtube_link": "https://youtu.be/T-44KNDKkSQ",
                                    "youtube_scheduled": True,
                                    "route": {
                                        "url": "https://studio.youtube.com/video/T-44KNDKkSQ/edit",
                                        "title": "视频详细信息 - YouTube Studio",
                                    },
                                },
                            },
                            "publication_field_snapshot": {
                                **expected_request_fields,
                                "body": "",
                                "hashtags": [],
                                "media_items_count": 0,
                            },
                            "publication_audit": {
                                "verified": True,
                                "required_unverified": [],
                                "required_reupload": [],
                                "issues": [],
                                "summary": {"status": "ok"},
                                "optional_missing": ["tags"],
                            },
                            "final_publish": {
                                "platform": "youtube",
                                "scheduled": True,
                                "receipt_like": True,
                                "receipt_target_bound": True,
                                "receipt_binding_source": "youtube_studio_editor_link",
                                "post_publish_surface": "youtube_studio_editor_receipt",
                                "external_url": "https://youtu.be/T-44KNDKkSQ",
                                "material_integrity_complete": False,
                            },
                            "publication_content_signature": {
                                "value": "sig-yt-scheduled-1",
                                "fields": {"title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手"},
                            },
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["youtube"],
        expected_statuses={"scheduled_pending"},
        expected_platform_manifest={
            "youtube": {
                "adapter": "browser_agent",
                "content_signature": "sig-yt-scheduled-1",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "passed"
    assert terminal_failure is False
    assert failures == []
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["strict_contract_verified"] is True
    assert "content_plan_fill_gaps" not in summaries[0]["strict_contract_reasons"]
    assert "content_plan_fill_gaps_deferred" in summaries[0]["strict_contract_reasons"]


def test_evaluate_progress_marks_youtube_editor_runtime_pending_summary():
    request_payload = {
        "platform": "youtube",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "youtube",
                "status": "processing",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "status": "processing",
                        "progress": {
                            "route": {
                                "url": "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
                                "title": "频道内容 - YouTube Studio",
                            },
                            "publication_field_snapshot": expected_request_fields,
                            "publication_audit": {
                                "verified": False,
                                "required_unverified": ["upload_ready"],
                                "required_reupload": ["upload_ready"],
                            },
                            "material_integrity": {
                                "verified": False,
                                "verification_reason": "editor_surface_runtime_timeout",
                                "failures": [],
                                "fields": {
                                    "upload_ready": {"actual": "not_ready", "verified": False},
                                },
                            },
                        },
                        "result": {
                            "error": {"code": "youtube_pre_publish_upload_pending"},
                            "recovery_overrides": {
                                "recovery_mode": "prepublish_resume",
                                "clear_draft_context": False,
                                "force_publish_page_refresh": True,
                                "prepare_only_current_page": True,
                                "verify_media_upload": True,
                                "wait_for_publish_confirmation": True,
                            },
                        },
                    },
                    "error_code": "youtube_pre_publish_upload_pending",
                },
                "error_code": "youtube_pre_publish_upload_pending",
                "runs": [],
            }
        ],
        targets=["youtube"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "youtube": {
                "adapter": "browser_agent",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "running"
    assert terminal_failure is False
    assert failures
    assert "youtube" in failures[0].lower()
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["pre_publish_upload_pending"] is True
    assert summaries[0]["verification_reason"] == "editor_surface_runtime_timeout"


def test_evaluate_progress_marks_upload_not_applied_summary():
    request_payload = {
        "platform": "kuaishou",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "kuaishou",
                "status": "needs_human",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "status": "needs_human",
                        "progress": {
                            "publication_field_snapshot": expected_request_fields,
                            "material_integrity": {
                                "verified": False,
                                "verification_reason": "upload_failed",
                                "upload_readiness": {
                                    "ready": False,
                                    "failed": True,
                                    "failure_reason": "upload_not_applied",
                                },
                            },
                        },
                        "error": {
                            "code": "kuaishou_media_upload_failed",
                            "details": {"failure_reason": "upload_not_applied"},
                        },
                    },
                    "error_code": "kuaishou_media_upload_failed",
                },
                "error_code": "kuaishou_media_upload_failed",
                "runs": [],
            }
        ],
        targets=["kuaishou"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "kuaishou": {
                "adapter": "browser_agent",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "failed"
    assert terminal_failure is True
    assert summaries[0]["upload_not_applied"] is True
    assert summaries[0]["upload_failure_reason"] == "upload_not_applied"


def test_evaluate_progress_marks_route_auth_required_summary():
    request_payload = {
        "platform": "wechat-channels",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "wechat-channels",
                "status": "needs_human",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "status": "needs_human",
                        "progress": {
                            "publication_field_snapshot": expected_request_fields,
                            "material_integrity": {
                                "verified": False,
                                "verification_reason": "auth_required",
                            },
                        },
                        "result": {
                            "error": {"code": "wechat-channels_route_auth_required"},
                        },
                    },
                    "error_code": "wechat-channels_route_auth_required",
                },
                "error_code": "wechat-channels_route_auth_required",
                "runs": [],
            }
        ],
        targets=["wechat-channels"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "wechat-channels": {
                "adapter": "browser_agent",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "failed"
    assert terminal_failure is True
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert summaries[0]["route_auth_required"] is True


def test_evaluate_progress_marks_adapter_mismatch_without_crashing():
    request_payload = {
        "platform": "douyin",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "正文",
        "hashtags": ["tag-a"],
        "display_hashtags": ["#tag-a"],
        "structured_tags": ["tag-a"],
        "content_kind": "video",
    }
    expected_request_fields = release_gate._extract_request_payload_fields(request_payload)
    status, failures, summaries, terminal_failure, recoverable_platforms, recoverable_failures = release_gate._evaluate_progress(
        [
            {
                "platform": "douyin",
                "status": "processing",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {},
                "runs": [],
            }
        ],
        targets=["douyin"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "douyin": {
                "adapter": "legacy_adapter",
                "request_fields": expected_request_fields,
            }
        },
    )

    assert status == "failed"
    assert terminal_failure is True
    assert recoverable_platforms == []
    assert recoverable_failures == []
    assert failures
    assert summaries[0]["expected_adapter"] == "legacy_adapter"
    assert summaries[0]["attempt_adapter"] == "browser_agent"
    assert "adapter_mismatch" in summaries[0]["strict_contract_reasons"]


def test_evaluate_progress_marks_empty_response_snapshot_untrusted_for_terminal_needs_human():
    request_payload = {
        "platform": "xiaohongshu",
        "adapter": "browser_agent",
        "title": "hello",
        "body": "body",
        "declaration": "原创声明",
        "content_kind": "video",
        "hashtags": ["tag1"],
        "display_hashtags": ["#tag1"],
        "structured_tags": ["tag1"],
        "native_topics": [],
        "category": None,
        "collection": {"name": "合集"},
        "cover_path": "E:/cover.jpg",
        "copy_material": {"primary_title": "hello"},
        "visibility_or_publish_mode": "scheduled",
        "scheduled_publish_at": "2026-05-31T21:00",
        "ui_control_semantics": {
            "schedule_publish": True,
            "collection_select": True,
        },
        "platform_specific_overrides": {},
        "media_urls": ["E:/video.mp4"],
        "media_items_count": 1,
        "publication_plan_signature": {
            "value": "sig-1",
            "fields": {"title": "hello"},
        },
    }
    status, failures, summaries, terminal_failure, _, _ = release_gate._evaluate_progress(
        [
            {
                "platform": "xiaohongshu",
                "status": "needs_human",
                "run_status": "needs_human",
                "provider_status": "needs_human",
                "error_code": "draft_clear_failed",
                "adapter": "browser_agent",
                "request_payload": request_payload,
                "response_payload": {
                    "task": {
                        "task_id": "task-1",
                        "status": "needs_human",
                        "result": {
                            "fields": {
                                "title": "",
                                "body": "",
                                "hashtags": [],
                                "collection": None,
                                "cover_path": None,
                                "scheduled_publish_at": None,
                                "ui_control_semantics": {
                                    "schedule_publish": False,
                                    "collection_select": False,
                                },
                            }
                        },
                        "error": {
                            "code": "draft_clear_failed",
                            "message": "draft clear failed",
                        },
                    }
                },
                "runs": [],
            }
        ],
        targets=["xiaohongshu"],
        expected_statuses={"published", "scheduled_pending"},
        expected_platform_manifest={
            "xiaohongshu": {
                "adapter": "browser_agent",
                "content_signature": "sig-1",
                "request_fields": {
                    key: value
                    for key, value in request_payload.items()
                    if key != "publication_plan_signature"
                },
            }
        },
    )

    assert status == "failed"
    assert terminal_failure is True
    assert failures
    assert summaries[0]["request_fields_snapshot_trusted"] is False
    assert summaries[0]["actual_request_fields_snapshot_source"] == "response_payload"


def test_build_real_release_gate_plan_summary_normalizes_targets_and_note() -> None:
    summary = release_gate._build_real_release_gate_plan_summary(
        publish_ready=True,
        created_attempts=[{"attempt_id": "1"}, "attempt-2", ""],
        plan_targets=["DouYin", "douyin", "x_post", ""],
        note=" deduped_before_publish ",
    )

    assert summary == {
        "publish_ready": True,
        "created_attempts": ["{'attempt_id': '1'}", "attempt-2"],
        "plan_targets": ["douyin", "x-post"],
        "note": "deduped_before_publish",
    }


def test_build_partial_created_attempt_failures_surfaces_active_attempt_skip() -> None:
    failures = release_gate._build_partial_created_attempt_failures(
        ["douyin", "xiaohongshu"],
        [{"platform": "douyin", "id": "attempt-1"}],
        [
            {
                "platform": "xiaohongshu",
                "reason": "active_attempt_exists",
                "attempt_id": "attempt-2",
                "status": "processing",
                "run_status": "processing",
                "error_code": "draft_clear_failed",
            }
        ],
    )

    assert failures == [
        "xiaohongshu: 已存在活跃发布 attempt，当前批次未重新建任务（status=processing, run_status=processing, attempt_id=attempt-2, error_code=draft_clear_failed）"
    ]


def test_build_active_attempt_receipt_rebind_targets_promotes_active_attempt_skip() -> None:
    targets = release_gate._build_active_attempt_receipt_rebind_targets(
        {
            "targets": [
                {
                    "platform": "toutiao",
                    "platform_specific_overrides": {
                        "recovery_mode": "draft_reset",
                        "clear_draft_context": True,
                    },
                },
                {"platform": "douyin"},
            ]
        },
        [
            {
                "platform": "toutiao",
                "reason": "active_attempt_exists",
                "attempt_id": "attempt-1",
                "status": "submitted",
            }
        ],
    )

    assert len(targets) == 1
    assert targets[0]["platform"] == "toutiao"
    assert targets[0]["platform_specific_overrides"] == {
        "recovery_mode": "receipt_rebind",
        "clear_draft_context": False,
        "force_publish_page_refresh": True,
        "verification_only_current_page": True,
        "verify_media_upload": True,
        "wait_for_publish_confirmation": True,
    }


def test_build_active_attempt_receipt_rebind_targets_ignores_non_active_skips() -> None:
    targets = release_gate._build_active_attempt_receipt_rebind_targets(
        {"targets": [{"platform": "toutiao"}]},
        [
            {
                "platform": "toutiao",
                "reason": "platform_scope_mismatch",
            }
        ],
    )

    assert targets == []


def test_build_terminal_publication_verification_surfaces_duplicate_recommendations() -> None:
    verification = release_gate._build_terminal_publication_verification(
        note="duplicate_history_gate_failed",
        plan_contract_checks=[],
        failures=["douyin: 命中历史重复发布风险 -> 标题 [multiple_active_attempts]"],
        duplicate_history_gate={
            "groups": [
                {
                    "platform": "douyin",
                }
            ]
        },
    )

    assert verification["note"] == "duplicate_history_gate_failed"
    assert verification["summary_status"] == "failed"
    assert verification["platform_summaries"] == []
    assert verification["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "duplicate_history_gate_failed",
            "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
            "auto_remediable": False,
        }
    ]
    assert verification["recovery_index"]["issue_counts"] == {"duplicate_history_gate_failed": 1}


def test_build_terminal_publication_verification_surfaces_preflight_recommendations() -> None:
    verification = release_gate._build_terminal_publication_verification(
        note="preflight_failed",
        plan_contract_checks=[],
        failures=["缺少目标平台发布页标签: douyin", "CDP 不可达"],
        agent_ready={"ready": False, "code": "missing_profile_id", "message": "缺少 profile"},
        live_check={
            "cdp": {
                "connected": False,
                "platform_checks": {
                    "douyin": {"status": "missing"},
                },
            }
        },
    )

    issues = {item["issue"] for item in verification["recommendations"]}
    assert issues == {"browser_agent_not_ready", "cdp_unreachable", "missing_publish_tab"}
    assert verification["recovery_index"]["auto_recoverable_recommendations"] == 3


@pytest.mark.asyncio
async def test_real_release_gate_blocks_on_duplicate_history_gate(monkeypatch: pytest.MonkeyPatch):
    async def _fake_duplicate_history_gate_report(**_: object) -> dict[str, object]:
        return {
            "status": "failed",
            "failures": ["douyin: 命中历史重复发布风险 -> 标题 [multiple_active_attempts]"],
            "allow_republish": False,
        }

    monkeypatch.setattr(release_gate, "build_duplicate_history_gate_report", _fake_duplicate_history_gate_report)

    report = await release_gate._run_real_publish_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        media_path="E:/media/maxace4.mp4",
        platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        timeout=12,
        poll_interval=2,
        max_wait_seconds=180,
        require_tabs=True,
        expected_status="published,scheduled_pending",
        allow_republish=False,
        allow_anonymous_profile=False,
        auto_recover_codes=set(),
        max_recoveries_per_platform=1,
        content_suffix="",
        platform_packaging={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            }
        },
    )

    assert report["status"] == "failed"
    assert report["agent_ready"]["code"] == "duplicate_history_gate_failed"
    assert report["duplicate_history_gate"]["status"] == "failed"
    assert any("历史重复发布风险" in item for item in report["failures"])
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "duplicate_history_gate_failed",
            "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
            "auto_remediable": False,
        }
    ]
    assert report["publication_verification"]["recovery_index"]["issue_counts"] == {
        "duplicate_history_gate_failed": 1
    }


@pytest.mark.asyncio
async def test_real_release_gate_dedupe_only_returns_non_publishable_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_duplicate_history_gate_report(**_: object) -> dict[str, object]:
        return {
            "status": "passed",
            "failures": [],
            "allow_republish": False,
            "checked_platforms": ["douyin"],
        }

    async def _fake_published_platforms_for_media(**_: object) -> list[str]:
        return ["douyin"]

    monkeypatch.setattr(release_gate, "build_duplicate_history_gate_report", _fake_duplicate_history_gate_report)
    monkeypatch.setattr(release_gate, "_published_platforms_for_media", _fake_published_platforms_for_media)

    report = await release_gate._run_real_publish_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        media_path="E:/media/maxace4.mp4",
        platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        timeout=12,
        poll_interval=2,
        max_wait_seconds=180,
        require_tabs=True,
        expected_status="published,scheduled_pending",
        allow_republish=False,
        allow_anonymous_profile=False,
        auto_recover_codes=set(),
        max_recoveries_per_platform=1,
        content_suffix="",
        platform_packaging={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            }
        },
    )

    assert report["status"] == "passed"
    assert report["agent_ready"]["code"] == "dedupe_only"
    assert report["plan"] == {
        "publish_ready": False,
        "created_attempts": [],
        "plan_targets": [],
        "note": "deduped_before_publish",
    }
    assert report["deduped_platforms"] == ["douyin"]
    assert report["platforms"] == []
    assert report["failures"] == []
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "deduped_before_publish",
            "operations": ["skip_publish", "review_existing_active_or_published_attempts"],
            "auto_remediable": False,
        }
    ]


@pytest.mark.asyncio
async def test_real_release_gate_reports_platform_outside_packaging_scope() -> None:
    report = await release_gate._run_real_publish_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        media_path="E:/media/maxace4.mp4",
        platforms=["douyin", "toutiao"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        timeout=12,
        poll_interval=2,
        max_wait_seconds=180,
        require_tabs=True,
        expected_status="published,scheduled_pending",
        allow_republish=False,
        allow_anonymous_profile=False,
        auto_recover_codes=set(),
        max_recoveries_per_platform=1,
        content_suffix="",
        platform_packaging={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            },
            "xiaohongshu": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            },
        },
        platform_packaging_scope={
            "requested_platforms": ["douyin", "xiaohongshu"],
            "covered_platforms": ["douyin", "xiaohongshu"],
            "missing_requested_platforms": [],
        },
    )

    assert report["status"] == "failed"
    assert report["agent_ready"]["code"] == "missing_platform_packaging"
    assert any("toutiao" in item and "不在本期物料生成范围内" in item for item in report["failures"])


@pytest.mark.asyncio
async def test_real_release_gate_reports_requested_platform_missing_packaging_entry() -> None:
    report = await release_gate._run_real_publish_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        media_path="E:/media/maxace4.mp4",
        platforms=["douyin", "toutiao"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        timeout=12,
        poll_interval=2,
        max_wait_seconds=180,
        require_tabs=True,
        expected_status="published,scheduled_pending",
        allow_republish=False,
        allow_anonymous_profile=False,
        auto_recover_codes=set(),
        max_recoveries_per_platform=1,
        content_suffix="",
        platform_packaging={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            },
        },
        platform_packaging_scope={
            "requested_platforms": ["douyin", "toutiao"],
            "covered_platforms": ["douyin"],
            "missing_requested_platforms": ["toutiao"],
        },
    )

    assert report["status"] == "failed"
    assert report["agent_ready"]["code"] == "missing_platform_packaging"
    assert any("toutiao" in item and "未提供以下平台的发布文案" in item for item in report["failures"])


@pytest.mark.asyncio
async def test_real_release_gate_uses_longer_readiness_timeout_than_publish_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, int] = {}

    async def fake_duplicate_history_gate_report(**_: object) -> dict[str, object]:
        return {
            "status": "passed",
            "failures": [],
            "allow_republish": False,
            "checked_platforms": ["douyin"],
        }

    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        seen["agent_ready_timeout"] = int(kwargs.get("request_timeout_sec") or 0)
        return {
            "ready": False,
            "code": "browser_agent_unavailable",
            "message": "timeout",
            "health": {},
        }

    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        seen["run_checks_timeout"] = int(kwargs.get("request_timeout_sec") or 0)
        return {
            "generated_at": "2026-06-02T11:30:00+08:00",
            "agent_ready": {
                "ready": False,
                "code": "browser_agent_unavailable",
                "message": "timeout",
                "health": {},
            },
            "cdp": {
                "connected": True,
                "tab_count": 1,
                "platform_checks": {
                    "douyin": {
                        "status": "found",
                        "tab_id": "tab-1",
                        "tab_url": "https://creator.douyin.com/creator-micro/content/post/video",
                        "tab_title": "抖音创作者中心",
                        "open_tabs_count": 1,
                    }
                },
            },
            "probe_inventory": {"checked": False, "status": "skipped", "platforms": {}, "failures": []},
            "packaging": {"checked": False, "status": "skipped", "platform_checks": {}, "manual_handoff_targets": [], "failures": []},
            "manual_handoff_targets": [],
            "failures": [],
            "all_tabs": [],
        }

    monkeypatch.setattr(release_gate, "build_duplicate_history_gate_report", fake_duplicate_history_gate_report)
    monkeypatch.setattr(release_gate, "check_publication_browser_agent_ready", fake_agent_ready)
    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    report = await release_gate._run_real_publish_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        media_path="E:/media/maxace4.mp4",
        platforms=["douyin"],
        target_profile_ids=[],
        timeout=12,
        poll_interval=2,
        max_wait_seconds=180,
        require_tabs=True,
        expected_status="published,scheduled_pending",
        allow_republish=False,
        allow_anonymous_profile=True,
        auto_recover_codes=set(),
        max_recoveries_per_platform=1,
        content_suffix="",
        platform_packaging={
            "douyin": {
                "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                "description": "正文",
                "tags": ["EDC折刀"],
            }
        },
    )

    assert seen["agent_ready_timeout"] == 30
    assert seen["run_checks_timeout"] == 30
    assert report["status"] == "failed"
    assert report["failures"] == ["browser-agent 未就绪: browser_agent_unavailable timeout"]


def test_build_creator_profile_does_not_treat_creator_profile_id_as_browser_profile_id() -> None:
    profile = release_gate._build_creator_profile(
        ["youtube"],
        ["demo-credential-ref"],
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
    )

    assert profile["id"] == "demo-credential-ref"
    credential = profile["creator_profile"]["publishing"]["platform_credentials"][0]
    assert credential["credential_ref"] == "demo-credential-ref"
    assert credential["browser_profile_id"] == ""


def test_build_creator_profile_preserves_explicit_browser_profile_binding_without_release_gate_fallback() -> None:
    profile = release_gate._build_creator_profile(
        ["douyin"],
        ["browser-profile:chrome:demo-profile-a"],
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        attached_profile_binding={
            "browser": "chrome",
            "user_data_dir": "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            "profile_directory": "Profile 2",
            "profile_id": "browser-profile:chrome:demo-profile-a",
        },
    )

    assert profile["id"] == "release-gate::browser-profile:chrome:demo-profile-a"
    credential = profile["creator_profile"]["publishing"]["platform_credentials"][0]
    assert credential["credential_ref"] == "browser-profile:chrome:demo-profile-a"
    assert credential["browser_profile_id"] == "browser-profile:chrome:demo-profile-a"
    assert credential["browser_binding"]["profile_id"] == "browser-profile:chrome:demo-profile-a"
    assert credential["browser_binding"]["user_data_dir"] == "C:/Users/demo/AppData/Local/Google/Chrome/User Data"
