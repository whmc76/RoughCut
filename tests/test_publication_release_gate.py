from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SMOKE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_minimax_publication_cdp_smoke.py"
_SMOKE_SPEC = importlib.util.spec_from_file_location("run_minimax_publication_cdp_smoke", _SMOKE_SCRIPT_PATH)
assert _SMOKE_SPEC and _SMOKE_SPEC.loader
smoke = importlib.util.module_from_spec(_SMOKE_SPEC)
_SMOKE_SPEC.loader.exec_module(smoke)

_RELEASE_GATE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_publication_release_gate.py"
_RELEASE_GATE_SPEC = importlib.util.spec_from_file_location("run_publication_release_gate", _RELEASE_GATE_SCRIPT_PATH)
assert _RELEASE_GATE_SPEC and _RELEASE_GATE_SPEC.loader
release_gate = importlib.util.module_from_spec(_RELEASE_GATE_SPEC)
_RELEASE_GATE_SPEC.loader.exec_module(release_gate)


def test_resolve_platform_packaging_prefers_real_packaging_over_fixture(tmp_path: Path) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "douyin",
      "primary_title": "SMART COPY TITLE",
      "body": "smart body",
      "tags": ["smart"]
    }
  ]
}""",
        encoding="utf-8",
    )
    platform_packaging = tmp_path / "platform-packaging.json"
    platform_packaging.write_text(
        """{
  "platforms": {
    "douyin": {
      "primary_title": "REAL PACKAGING TITLE",
      "description": "real body",
      "tags": ["real"]
    }
  }
}""",
        encoding="utf-8",
    )

    payload, sources = smoke._resolve_platform_packaging(
        platforms=["douyin"],
        material_json=str(material_json),
        platform_packaging="",
    )

    assert payload["platforms"]["douyin"]["primary_title"] == "REAL PACKAGING TITLE"
    assert sources["source"] == "platform_packaging"
    assert sources["material_json_path"] == str(material_json)
    assert sources["platform_packaging_path"] == str(platform_packaging)


def test_resolve_platform_packaging_backfills_missing_requested_platform_from_material_when_sibling_packaging_is_partial(
    tmp_path: Path,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "bilibili",
      "primary_title": "B站标题",
      "body": "B站正文",
      "tags": ["EDC"]
    }
  ]
}""",
        encoding="utf-8",
    )
    platform_packaging = tmp_path / "platform-packaging.json"
    platform_packaging.write_text(
        """{
  "platforms": {
    "douyin": {
      "primary_title": "抖音标题",
      "description": "抖音正文",
      "publish_ready": true
    }
  }
}""",
        encoding="utf-8",
    )

    payload, sources = smoke._resolve_platform_packaging(
        platforms=["bilibili"],
        material_json=str(material_json),
        platform_packaging="",
    )

    assert payload["platforms"]["bilibili"]["primary_title"] == "B站标题"
    assert sources["source"] == "platform_packaging+material_json"


def test_platform_packaging_fixture_uses_shared_root_publish_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "publication_packaging_payload_publish_ready", lambda packaging: False)

    payload = smoke._platform_packaging(["douyin"])

    assert payload["publish_ready"] is False


def test_backend_smoke_status_treats_manual_handoff_targets_as_manual_handoff_even_when_publish_ready_is_stale_true() -> None:
    status = smoke._backend_smoke_status(
        plan={
            "publish_ready": True,
            "manual_handoff_ready": False,
            "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号。"],
            "targets": [],
            "manual_handoff_targets": [{"platform": "wechat-channels"}],
        },
        submit_result={"created_attempts": []},
        posted_tasks=[],
        attempts=[],
        platform_count=1,
        fake_status="queued",
    )

    assert status == "manual_handoff"


def test_evaluate_failure_surfaces_manual_handoff_contract_state() -> None:
    failures = release_gate._evaluate_failure(
        {"failures": []},
        {
            "status": "failed",
            "plan_status": "manual_handoff",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": True,
            "plan_blocked_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
            "created_attempts": 0,
        },
        False,
        contract_success_status="draft_created",
    )

    assert failures == ["发布计划要求人工接管，未达到自动一键发布条件"]


def test_evaluate_failure_surfaces_plan_blocked_reasons_before_generic_smoke_failure() -> None:
    failures = release_gate._evaluate_failure(
        {"failures": []},
        {
            "status": "failed",
            "plan_status": "blocked",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": False,
            "plan_blocked_reasons": ["缺少 live_publish_preflight", "缺少封面"],
            "created_attempts": 0,
        },
        False,
        contract_success_status="draft_created",
    )

    assert failures == ["缺少 live_publish_preflight", "缺少封面"]


def test_evaluate_failure_prefers_rich_backend_manual_handoff_status() -> None:
    failures = release_gate._evaluate_failure(
        {"failures": []},
        {
            "status": "manual_handoff",
            "plan_status": "",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": False,
            "plan_blocked_reasons": [],
            "created_attempts": 0,
        },
        False,
        contract_success_status="draft_created",
    )

    assert failures == ["发布计划要求人工接管，未达到自动一键发布条件"]


def test_evaluate_failure_prefers_rich_backend_blocked_status() -> None:
    failures = release_gate._evaluate_failure(
        {"failures": []},
        {
            "status": "blocked",
            "plan_status": "",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": False,
            "plan_blocked_reasons": ["缺少 live_publish_preflight"],
            "created_attempts": 0,
        },
        False,
        contract_success_status="draft_created",
    )

    assert failures == ["缺少 live_publish_preflight"]


def test_build_release_gate_publication_verification_surfaces_manual_handoff_recommendation() -> None:
    verification = release_gate._build_release_gate_publication_verification(
        {"ready": True, "failures": []},
        {
            "status": "manual_handoff",
            "plan_status": "manual_handoff",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": True,
            "plan_targets": ["wechat-channels"],
            "plan_blocked_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
        },
        skip_backend_smoke=False,
        requested_platforms=["wechat-channels"],
        failures=["发布计划要求人工接管，未达到自动一键发布条件"],
    )

    assert verification["summary_status"] == "manual_handoff"
    assert verification["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]
    assert verification["recovery_index"]["issue_counts"] == {"manual_handoff_required": 1}


def test_build_release_gate_publication_verification_preserves_creator_session_visual_evidence() -> None:
    verification = release_gate._build_release_gate_publication_verification(
        {
            "ready": False,
            "failures": ["发布服务未就绪: browser_agent_creator_session_auth_required - 创作者会话未登录"],
            "creator_sessions": {
                "douyin": {
                    "platform": "douyin",
                    "ready": False,
                    "status": "auth_required",
                    "code": "douyin_route_auth_required",
                    "message": "创作者会话当前未登录或已失效。",
                    "verification_reason": "auth_required",
                    "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video", "title": "抖音创作者中心"},
                    "visual_evidence": {
                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/session-auth.png",
                        "capture_type": "screenshot",
                        "phase": "creator_session_probe",
                    },
                }
            },
        },
        {},
        skip_backend_smoke=True,
        requested_platforms=["douyin"],
        failures=["发布服务未就绪: browser_agent_creator_session_auth_required - 创作者会话未登录"],
    )

    assert verification["creator_sessions"]["douyin"]["status"] == "auth_required"
    assert verification["creator_session_visual_evidence_by_platform"]["douyin"]["capture_type"] == "screenshot"
    assert verification["creator_session_visual_evidence_by_platform"]["douyin"]["phase"] == "creator_session_probe"


def test_build_release_gate_publication_verification_preserves_probe_inventory_visual_evidence() -> None:
    verification = release_gate._build_release_gate_publication_verification(
        {
            "ready": True,
            "failures": [],
            "probe_inventory": {
                "checked": True,
                "status": "partial",
                "platforms": {
                    "douyin": {
                        "status": "ready",
                        "message": "当前页面已进入抖音发布路由。",
                        "route": {
                            "url": "https://creator.douyin.com/creator-micro/content/post/video",
                            "title": "抖音创作者中心",
                        },
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/probe.png",
                            "capture_type": "screenshot",
                            "phase": "probe_inventory",
                        },
                        "warnings": [],
                    }
                },
                "failures": [],
            },
        },
        {},
        skip_backend_smoke=True,
        requested_platforms=["douyin"],
        failures=[],
    )

    assert verification["probe_inventory"]["platforms"]["douyin"]["status"] == "ready"
    assert verification["probe_inventory_visual_evidence_by_platform"]["douyin"]["capture_type"] == "screenshot"
    assert verification["probe_inventory_visual_evidence_by_platform"]["douyin"]["phase"] == "probe_inventory"


def test_build_release_gate_publication_verification_surfaces_blocked_recommendation() -> None:
    verification = release_gate._build_release_gate_publication_verification(
        {"ready": True, "failures": []},
        {
            "status": "blocked",
            "plan_status": "blocked",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": False,
            "plan_targets": ["douyin"],
            "plan_blocked_reasons": ["缺少 live_publish_preflight", "缺少封面"],
        },
        skip_backend_smoke=False,
        requested_platforms=["douyin"],
        failures=["缺少 live_publish_preflight", "缺少封面"],
    )

    assert verification["summary_status"] == "blocked"
    assert verification["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "plan_blocked",
            "operations": ["repair_material_contract", "rerun_backend_smoke"],
            "auto_remediable": True,
        }
    ]
    assert verification["recovery_index"]["issue_counts"] == {"plan_blocked": 1}


def test_build_release_gate_publication_verification_surfaces_platform_scope_mismatch_recommendation() -> None:
    verification = release_gate._build_release_gate_publication_verification(
        {
            "ready": False,
            "failures": ["发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
        },
        {},
        skip_backend_smoke=True,
        requested_platforms=["kuaishou"],
        failures=["发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
    )

    assert verification["summary_status"] == "failed"
    assert verification["recommendations"] == [
        {
            "platform": "kuaishou",
            "issue": "platform_scope_mismatch",
            "operations": ["regenerate_platform_material", "restrict_requested_platforms"],
            "auto_remediable": True,
        }
    ]
    assert verification["recovery_index"]["issue_counts"] == {"platform_scope_mismatch": 1}


def test_build_release_gate_report_surfaces_mitigation_and_suggestions() -> None:
    report = release_gate._build_release_gate_report(
        browser_agent_base_url="http://127.0.0.1:49310",
        cdp_url="http://127.0.0.1:9222",
        platforms=["wechat-channels"],
        target_profile_ids=[],
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        live_gate={"ready": True, "failures": []},
        backend_smoke={
            "status": "manual_handoff",
            "plan_status": "manual_handoff",
            "plan_publish_ready": False,
            "plan_manual_handoff_ready": True,
            "plan_targets": ["wechat-channels"],
            "plan_blocked_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
        },
        skip_backend_smoke=False,
        expectation_report={"scope": "backend_contract_simulation"},
        failures=["发布计划要求人工接管，未达到自动一键发布条件"],
    )

    assert report["status"] == "failed"
    assert report["publication_verification"]["summary_status"] == "manual_handoff"
    assert report["suggestions"] == ["检测到发布计划要求人工接管，请打开登录页并转入人工发布。"]
    assert report["mitigation"]["playbook"]["manual_handoff_required"] == [
        "continue_manual_publish",
        "open_manual_login",
    ]


@pytest.mark.asyncio
async def test_run_live_release_gate_preserves_creator_session_visual_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        return {
            "agent_ready": {
                "ready": False,
                "code": "browser_agent_creator_session_auth_required",
                "message": "创作者会话当前未登录或已失效。",
                "health": {
                    "creator_sessions": {
                        "douyin": {
                            "platform": "douyin",
                            "ready": False,
                            "status": "auth_required",
                            "code": "douyin_route_auth_required",
                            "message": "创作者会话当前未登录或已失效。",
                            "verification_reason": "auth_required",
                            "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video", "title": "抖音创作者中心"},
                            "visual_evidence": {
                                "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/session-auth.png",
                                "capture_type": "screenshot",
                                "phase": "creator_session_probe",
                            },
                        }
                    }
                },
            },
            "cdp": {"connected": True, "platform_checks": {"douyin": {"status": "found"}}},
        }

    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    result = await release_gate._run_live_release_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:test"],
        allow_anonymous_profile=False,
        timeout=5,
        require_tabs=True,
    )

    assert result["creator_sessions"]["douyin"]["status"] == "auth_required"
    assert result["creator_sessions"]["douyin"]["visual_evidence"]["capture_type"] == "screenshot"


@pytest.mark.asyncio
async def test_run_live_release_gate_preserves_probe_inventory_visual_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        return {
            "agent_ready": {
                "ready": True,
                "code": "",
                "message": "",
                "health": {"creator_sessions": {}},
            },
            "probe_inventory": {
                "checked": True,
                "status": "partial",
                "platforms": {
                    "douyin": {
                        "status": "ready",
                        "message": "当前页面已进入抖音发布路由。",
                        "route": {
                            "url": "https://creator.douyin.com/creator-micro/content/post/video",
                            "title": "抖音创作者中心",
                        },
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/probe.png",
                            "capture_type": "screenshot",
                            "phase": "probe_inventory",
                        },
                        "warnings": [],
                    }
                },
                "failures": [],
            },
            "cdp": {"connected": True, "platform_checks": {"douyin": {"status": "found"}}},
        }

    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    result = await release_gate._run_live_release_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:test"],
        allow_anonymous_profile=False,
        timeout=5,
        require_tabs=True,
    )

    assert result["probe_inventory"]["platforms"]["douyin"]["status"] == "ready"
    assert result["probe_inventory"]["platforms"]["douyin"]["visual_evidence"]["capture_type"] == "screenshot"


@pytest.mark.asyncio
async def test_run_live_release_gate_preserves_probe_gate_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        return {
            "agent_ready": {
                "ready": True,
                "code": "ready",
                "message": "",
                "health": {"creator_sessions": {}},
            },
            "probe_inventory": {
                "checked": True,
                "status": "partial",
                "platforms": {
                    "xiaohongshu": {
                        "status": "partial",
                        "message": "当前页面缺少发布前必要参数面。",
                        "route": {
                            "url": "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
                            "title": "小红书创作服务平台",
                        },
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/xiaohongshu/probe.png",
                            "capture_type": "screenshot",
                            "phase": "probe_inventory",
                        },
                        "warnings": [],
                    }
                },
                "failures": [],
            },
            "cdp": {"connected": True, "platform_checks": {"xiaohongshu": {"status": "found"}}},
            "failures": ["xiaohongshu: 实际发布页缺少关键参数面 cover, declaration"],
        }

    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    result = await release_gate._run_live_release_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        platforms=["xiaohongshu"],
        target_profile_ids=["browser-profile:chrome:test"],
        allow_anonymous_profile=False,
        timeout=5,
        require_tabs=True,
    )

    assert result["failures"] == ["xiaohongshu: 实际发布页缺少关键参数面 cover, declaration"]


@pytest.mark.asyncio
async def test_run_live_release_gate_ignores_manual_handoff_platform_for_require_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        return {
            "request": {
                "live_publish_platforms": ["douyin"],
            },
            "agent_ready": {
                "ready": True,
                "code": "ready",
                "message": "",
                "health": {"creator_sessions": {}},
            },
            "packaging": {
                "checked": True,
                "status": "passed",
                "platform_checks": {
                    "douyin": {"status": "ready", "message": "发布物料合同就绪。"},
                    "wechat-channels": {"status": "manual_handoff", "message": "该平台当前走人工接管，不进入自动一键发布。"},
                },
                "manual_handoff_targets": [
                    {"platform": "wechat-channels", "login_url": "https://channels.weixin.qq.com/login.html"}
                ],
                "failures": [],
            },
            "probe_inventory": {"checked": False, "status": "skipped", "platforms": {}, "failures": []},
            "cdp": {
                "connected": True,
                "platform_checks": {
                    "douyin": {"status": "found"},
                    "wechat-channels": {"status": "manual_handoff"},
                },
            },
            "failures": [],
        }

    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    result = await release_gate._run_live_release_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        platforms=["douyin", "wechat-channels"],
        target_profile_ids=["browser-profile:chrome:test"],
        allow_anonymous_profile=False,
        timeout=5,
        require_tabs=True,
    )

    assert result["ready"] is True
    assert result["failures"] == []
    assert result["creator_sessions"] == {}
    assert result["packaging"]["manual_handoff_targets"] == [
        {"platform": "wechat-channels", "login_url": "https://channels.weixin.qq.com/login.html"}
    ]


@pytest.mark.asyncio
async def test_run_live_release_gate_fails_closed_on_packaging_scope_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_checks(**kwargs: object) -> dict[str, object]:
        return {
            "agent_ready": {
                "ready": True,
                "code": "ready",
                "message": "",
                "health": {"creator_sessions": {}},
            },
            "probe_inventory": {
                "checked": True,
                "status": "partial",
                "platforms": {
                    "kuaishou": {
                        "status": "partial",
                        "message": "已采集当前页参数结构快照。",
                        "route": {
                            "url": "https://cp.kuaishou.com/article/publish/video",
                            "title": "快手创作者服务平台",
                        },
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/20260602/kuaishou/probe.png",
                            "capture_type": "screenshot",
                            "phase": "probe_inventory",
                        },
                        "warnings": [],
                    }
                },
                "failures": [],
            },
            "packaging": {
                "checked": True,
                "status": "failed",
                "source": "platform_packaging",
                "platform_checks": {
                    "kuaishou": {
                        "status": "missing",
                        "message": "该平台不在本期物料合同覆盖范围内。当前仅覆盖平台 -> douyin, xiaohongshu",
                    }
                },
                "failures": ["发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
            },
            "cdp": {"connected": True, "platform_checks": {"kuaishou": {"status": "found"}}},
            "failures": ["发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
        }

    monkeypatch.setattr(release_gate, "_run_checks", fake_run_checks)

    result = await release_gate._run_live_release_gate(
        browser_agent_base_url="http://127.0.0.1:49310",
        auth_token="",
        cdp_url="http://127.0.0.1:9222",
        platforms=["kuaishou"],
        target_profile_ids=["browser-profile:chrome:test"],
        allow_anonymous_profile=False,
        timeout=5,
        require_tabs=True,
        material_json="E:/material/smart-copy.json",
        platform_packaging="E:/material/platform-packaging.json",
    )

    assert result["ready"] is False
    assert result["packaging"]["status"] == "failed"
    assert result["packaging"]["platform_checks"]["kuaishou"]["status"] == "missing"
    assert result["failures"] == ["发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"]


def test_backend_smoke_status_preserves_manual_handoff_and_blocked_states() -> None:
    manual_handoff_status = smoke._backend_smoke_status(
        plan={"status": "manual_handoff", "publish_ready": False, "manual_handoff_ready": True},
        submit_result={"created_attempts": []},
        posted_tasks=[],
        attempts=[],
        platform_count=1,
        fake_status="draft_created",
    )
    blocked_status = smoke._backend_smoke_status(
        plan={"status": "blocked", "publish_ready": False, "manual_handoff_ready": False},
        submit_result={"created_attempts": []},
        posted_tasks=[],
        attempts=[],
        platform_count=1,
        fake_status="draft_created",
    )

    assert manual_handoff_status == "manual_handoff"
    assert blocked_status == "blocked"


def test_backend_smoke_status_blocks_ready_plan_without_targets() -> None:
    status = smoke._backend_smoke_status(
        plan={"status": "ready", "publish_ready": True, "manual_handoff_ready": False, "targets": []},
        submit_result={"created_attempts": []},
        posted_tasks=[],
        attempts=[],
        platform_count=1,
        fake_status="draft_created",
    )

    assert status == "blocked"


def test_backend_smoke_status_uses_publishable_target_count_instead_of_requested_platform_count() -> None:
    status = smoke._backend_smoke_status(
        plan={
            "status": "ready",
            "publish_ready": True,
            "manual_handoff_ready": False,
            "targets": [
                {"platform": "douyin"},
                {"platform": "xiaohongshu"},
            ],
            "manual_handoff_targets": [{"platform": "wechat-channels"}],
        },
        submit_result={"created_attempts": [{}, {}]},
        posted_tasks=[{"platform": "douyin"}, {"platform": "xiaohongshu"}],
        attempts=[
            {"platform": "douyin", "status": "draft_created"},
            {"platform": "xiaohongshu", "status": "draft_created"},
        ],
        platform_count=3,
        fake_status="draft_created",
    )

    assert status == "passed"


@pytest.mark.asyncio
async def test_run_backend_contract_smoke_uses_real_platform_packaging_when_available(tmp_path: Path) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "douyin",
      "primary_title": "SMART COPY TITLE",
      "body": "smart body",
      "tags": ["smart"]
    }
  ]
}""",
        encoding="utf-8",
    )
    platform_packaging = tmp_path / "platform-packaging.json"
    platform_packaging.write_text(
        """{
  "platforms": {
    "douyin": {
      "titles": ["REAL PACKAGING TITLE"],
      "description": "real body",
      "tags": ["real"],
      "publish_ready": true
    }
  }
}""",
        encoding="utf-8",
    )

    report = await smoke._run_backend_contract_smoke(
        ["douyin"],
        tmp_path,
        "draft_created",
        publication_adapter="browser_agent",
        execution_mode="browser_agent",
        material_json=str(material_json),
        platform_packaging="",
    )

    assert report["status"] == "passed"
    assert report["platform_packaging_source"] == "platform_packaging"
    assert report["platform_packaging_path"] == str(platform_packaging)
    assert report["material_json_path"] == str(material_json)
    assert report["task_contracts"][0]["title"] == "REAL PACKAGING TITLE"
