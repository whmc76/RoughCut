from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_publication_preflight.py"
_SPEC = importlib.util.spec_from_file_location("run_publication_preflight", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
preflight = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(preflight)


@pytest.mark.asyncio
async def test_fetch_cdp_tabs_payload_retries_transient_connect_timeout() -> None:
    calls: list[str] = []

    async def fake_fetch_json(client: object, url: str) -> object:
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("timed out")
        return [{"id": "tab-1", "url": "https://creator.douyin.com/creator-micro/content/post/video"}]

    original = preflight._fetch_json
    preflight._fetch_json = fake_fetch_json
    try:
        result = await preflight._fetch_cdp_tabs_payload(object(), "http://127.0.0.1:9222", attempts=3, retry_delay_sec=0)
    finally:
        preflight._fetch_json = original

    assert isinstance(result, list)
    assert result[0]["id"] == "tab-1"
    assert len(calls) == 3
    assert calls[0].endswith("/json/list")
    assert calls[1].endswith("/json/version")
    assert calls[2].endswith("/json/list")


@pytest.mark.asyncio
async def test_fetch_cdp_tabs_payload_raises_after_retry_budget_exhausted() -> None:
    calls = 0

    async def fake_fetch_json(client: object, url: str) -> object:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("timed out")

    original = preflight._fetch_json
    original_fallback = preflight._fetch_cdp_tabs_payload_via_urllib
    preflight._fetch_json = fake_fetch_json
    preflight._fetch_cdp_tabs_payload_via_urllib = lambda cdp_url: (_ for _ in ()).throw(RuntimeError("fallback failed"))
    try:
        with pytest.raises(httpx.ConnectTimeout):
            await preflight._fetch_cdp_tabs_payload(object(), "http://127.0.0.1:9222", attempts=2, retry_delay_sec=0)
    finally:
        preflight._fetch_json = original
        preflight._fetch_cdp_tabs_payload_via_urllib = original_fallback

    assert calls == 3


@pytest.mark.asyncio
async def test_fetch_cdp_tabs_payload_falls_back_to_urllib_after_httpx_retry_failure() -> None:
    calls = 0

    async def fake_fetch_json(client: object, url: str) -> object:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("timed out")

    original = preflight._fetch_json
    original_fallback = preflight._fetch_cdp_tabs_payload_via_urllib
    preflight._fetch_json = fake_fetch_json
    preflight._fetch_cdp_tabs_payload_via_urllib = lambda cdp_url: [{"id": "urllib-tab"}]
    try:
        result = await preflight._fetch_cdp_tabs_payload(object(), "http://127.0.0.1:9222", attempts=2, retry_delay_sec=0)
    finally:
        preflight._fetch_json = original
        preflight._fetch_cdp_tabs_payload_via_urllib = original_fallback

    assert result == [{"id": "urllib-tab"}]
    assert calls == 3


@pytest.mark.asyncio
async def test_run_checks_preserves_probe_inventory_visual_evidence() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-douyin",
                "title": "抖音创作者中心",
                "url": "https://creator.douyin.com/creator-micro/content/post/video",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "probe_id": "probe-123",
            "generated_at": "2026-06-01T23:55:00+08:00",
            "platforms": {
                "douyin": {
                    "status": "ready",
                    "visual_evidence": {
                        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260601/douyin/editor.png",
                        "capture_type": "screenshot",
                        "phase": "probe_inventory",
                    },
                }
            },
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["douyin"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory

    assert report["probe_inventory"]["checked"] is True
    assert report["probe_inventory"]["status"] == "ok"
    assert report["probe_inventory"]["platforms"]["douyin"]["visual_evidence"]["artifact_path"].endswith("editor.png")
    assert report["cdp"]["platform_checks"]["douyin"]["visual_evidence"] == {
        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260601/douyin/editor.png",
        "capture_type": "screenshot",
        "phase": "probe_inventory",
    }


@pytest.mark.asyncio
async def test_run_checks_marks_cdp_connected_when_tab_fetch_succeeds_even_if_agent_health_is_empty() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": False,
            "code": "browser_agent_unavailable",
            "message": "timeout",
            "health": {},
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-douyin",
                "title": "抖音创作者中心",
                "url": "https://creator.douyin.com/creator-micro/content/post/video",
                "type": "page",
            }
        ]

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["douyin"],
            target_profile_ids=[],
            request_timeout_sec=3,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs

    assert report["agent_ready"]["ready"] is False
    assert report["cdp"]["connected"] is True
    assert report["cdp"]["platform_checks"]["douyin"]["status"] == "found"


@pytest.mark.asyncio
async def test_run_checks_blocks_when_probe_inventory_missing_required_surfaces() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-xhs",
                "title": "小红书创作服务平台",
                "url": "https://creator.xiaohongshu.com/new/note-manager",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        return {
            "status": "partial",
            "platforms": {
                "xiaohongshu": {
                    "status": "partial",
                    "route": {"url": "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video"},
                    "coverage": {
                        "missing_required_surfaces": [
                            {"key": "cover"},
                            {"key": "declaration"},
                        ]
                    },
                    "visual_evidence": {
                        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260601/xiaohongshu/probe.png",
                        "capture_type": "screenshot",
                        "phase": "probe_inventory",
                    },
                }
            },
        }

    def fake_packaging_preflight(**kwargs: object) -> dict[str, object]:
        return {
            "checked": True,
            "status": "passed",
            "platform_checks": {"xiaohongshu": {"status": "ready", "message": "发布物料合同就绪。"}},
            "manual_handoff_targets": [],
            "failures": [],
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    original_packaging_preflight = preflight._evaluate_packaging_preflight
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    preflight._evaluate_packaging_preflight = fake_packaging_preflight
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["xiaohongshu"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory
        preflight._evaluate_packaging_preflight = original_packaging_preflight

    assert report["failures"] == ["xiaohongshu: 实际发布页缺少关键参数面 cover, declaration"]
    assert report["cdp"]["platform_checks"]["xiaohongshu"]["probe_gate_blocked"] is True
    assert report["cdp"]["platform_checks"]["xiaohongshu"]["missing_required_surfaces"] == ["cover", "declaration"]


@pytest.mark.asyncio
async def test_run_checks_blocks_when_probe_inventory_route_not_ready() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-bili",
                "title": "哔哩哔哩创作中心",
                "url": "https://member.bilibili.com/platform/upload/video/frame",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        return {
            "status": "partial",
            "platforms": {
                "bilibili": {
                    "status": "route_not_ready",
                    "route": {"url": "https://member.bilibili.com/platform/upload/video/frame"},
                    "route_readiness": {
                        "blocked": True,
                        "status": "route_not_ready",
                        "reason": "publish_route_loading",
                    },
                    "coverage": {"missing_required_surfaces": [{"key": "cover"}]},
                }
            },
        }

    def fake_packaging_preflight(**kwargs: object) -> dict[str, object]:
        return {
            "checked": True,
            "status": "passed",
            "platform_checks": {"bilibili": {"status": "ready", "message": "发布物料合同就绪。"}},
            "manual_handoff_targets": [],
            "failures": [],
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    original_packaging_preflight = preflight._evaluate_packaging_preflight
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    preflight._evaluate_packaging_preflight = fake_packaging_preflight
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["bilibili"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory
        preflight._evaluate_packaging_preflight = original_packaging_preflight

    assert report["failures"] == ["bilibili: 实际发布页仍在加载中，编辑器尚未就绪。"]
    assert report["cdp"]["platform_checks"]["bilibili"]["probe_gate_blocked"] is True
    assert report["cdp"]["platform_checks"]["bilibili"]["missing_required_surfaces"] == []


@pytest.mark.asyncio
async def test_run_checks_excludes_manual_handoff_platforms_from_agent_ready_and_probe() -> None:
    observed_target_platforms: list[list[str]] = []
    observed_probe_platforms: list[list[str]] = []

    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        observed_target_platforms.append(list(kwargs.get("target_platforms") or []))
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-douyin",
                "title": "抖音创作者中心",
                "url": "https://creator.douyin.com/creator-micro/content/post/video",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        observed_probe_platforms.append(list(platforms))
        return {
            "status": "ok",
            "platforms": {
                "douyin": {
                    "status": "ready",
                    "visual_evidence": {
                        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/probe.png",
                        "capture_type": "screenshot",
                        "phase": "probe_inventory",
                    },
                }
            },
        }

    def fake_packaging_preflight(**kwargs: object) -> dict[str, object]:
        return {
            "checked": True,
            "status": "passed",
            "platform_checks": {
                "douyin": {"status": "ready", "message": "发布物料合同就绪。"},
                "wechat-channels": {"status": "manual_handoff", "message": "该平台当前走人工接管，不进入自动一键发布。"},
            },
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
            "failures": [],
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    original_packaging_preflight = preflight._evaluate_packaging_preflight
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    preflight._evaluate_packaging_preflight = fake_packaging_preflight
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["douyin", "wechat-channels"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory
        preflight._evaluate_packaging_preflight = original_packaging_preflight

    assert observed_target_platforms == [["douyin"]]
    assert observed_probe_platforms == [["douyin"]]
    assert report["request"]["live_publish_platforms"] == ["douyin"]
    assert report["cdp"]["platform_checks"]["wechat-channels"]["status"] == "manual_handoff"
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]


@pytest.mark.asyncio
async def test_run_checks_probe_only_does_not_fail_on_packaging_gate() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-douyin",
                "title": "抖音创作者中心",
                "url": "https://creator.douyin.com/creator-micro/content/post/video",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "platforms": {
                "douyin": {
                    "status": "ready",
                    "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video"},
                    "coverage": {"missing_required_surfaces": []},
                }
            },
        }

    def fake_packaging_preflight(**kwargs: object) -> dict[str, object]:
        return {
            "checked": True,
            "status": "report_only",
            "gate_enforced": False,
            "reported_failures": ["发布文案未就绪：douyin"],
            "platform_checks": {"douyin": {"status": "blocked", "message": "platform-packaging 标记为未就绪。"}},
            "manual_handoff_targets": [],
            "failures": [],
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    original_packaging_preflight = preflight._evaluate_packaging_preflight
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    preflight._evaluate_packaging_preflight = fake_packaging_preflight
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["douyin"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
            packaging_gate_enforced=False,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory
        preflight._evaluate_packaging_preflight = original_packaging_preflight

    assert report["failures"] == []
    assert report["packaging"]["status"] == "report_only"
    assert report["packaging"]["reported_failures"] == ["发布文案未就绪：douyin"]


@pytest.mark.asyncio
async def test_run_checks_surfaces_probe_inventory_fetch_failure() -> None:
    async def fake_agent_ready(**kwargs: object) -> dict[str, object]:
        return {
            "ready": True,
            "code": "ready",
            "message": "ok",
            "health": {
                "cdp_status": "ok",
                "capabilities": {
                    "inventory_probe": True,
                },
            },
        }

    async def fake_fetch_cdp_tabs_payload(client: object, cdp_url: str, **kwargs: object) -> list[dict[str, str]]:
        return [
            {
                "id": "tab-xhs",
                "title": "小红书创作服务平台",
                "url": "https://creator.xiaohongshu.com/publish",
                "type": "page",
            }
        ]

    async def fake_probe_inventory(
        client: object,
        browser_agent_base_url: str,
        auth_token: str,
        platforms: list[str],
    ) -> dict[str, object]:
        raise RuntimeError("probe timeout")

    def fake_packaging_preflight(**kwargs: object) -> dict[str, object]:
        return {
            "checked": True,
            "status": "report_only",
            "gate_enforced": False,
            "reported_failures": ["发布文案未就绪：xiaohongshu"],
            "platform_checks": {"xiaohongshu": {"status": "blocked", "message": "platform-packaging 标记为未就绪。"}},
            "manual_handoff_targets": [],
            "failures": [],
        }

    original_agent_ready = preflight.check_publication_browser_agent_ready
    original_fetch_tabs = preflight._fetch_cdp_tabs_payload
    original_probe_inventory = preflight._fetch_browser_agent_probe_inventory
    original_packaging_preflight = preflight._evaluate_packaging_preflight
    preflight.check_publication_browser_agent_ready = fake_agent_ready
    preflight._fetch_cdp_tabs_payload = fake_fetch_cdp_tabs_payload
    preflight._fetch_browser_agent_probe_inventory = fake_probe_inventory
    preflight._evaluate_packaging_preflight = fake_packaging_preflight
    try:
        report = await preflight._run_checks(
            browser_agent_base_url="http://127.0.0.1:49310",
            auth_token="",
            publication_adapter="browser_agent",
            cdp_url="http://127.0.0.1:9222",
            platforms=["xiaohongshu"],
            target_profile_ids=["browser-profile:chrome:test"],
            request_timeout_sec=3,
            packaging_gate_enforced=False,
        )
    finally:
        preflight.check_publication_browser_agent_ready = original_agent_ready
        preflight._fetch_cdp_tabs_payload = original_fetch_tabs
        preflight._fetch_browser_agent_probe_inventory = original_probe_inventory
        preflight._evaluate_packaging_preflight = original_packaging_preflight

    assert report["probe_inventory"]["status"] == "probe_failed"
    assert report["failures"] == ["browser-agent probe inventory 拉取失败：probe timeout"]


def test_evaluate_packaging_preflight_blocks_missing_required_surfaces(tmp_path: Path) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "douyin",
      "primary_title": "真实标题",
      "body": "真实正文",
      "publish_ready": true,
      "live_publish_preflight": {
        "status": "blocked",
        "missing_required_surfaces": ["cover", "collection"]
      }
    }
  ],
  "material_contract": {
    "platforms": {
      "douyin": {
        "blocking_reasons": []
      }
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(platforms=["douyin"], material_json=str(material_json))

    assert report["checked"] is True
    assert report["status"] == "failed"
    assert report["platform_checks"]["douyin"]["status"] == "blocked"
    assert report["platform_checks"]["douyin"]["missing_required_surfaces"] == ["cover", "collection"]
    assert report["failures"] == ["douyin: 缺少关键参数面 cover, collection"]


def test_evaluate_packaging_preflight_reports_but_does_not_fail_when_gate_disabled(tmp_path: Path) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "douyin": {
      "titles": ["真实标题"],
      "description": "真实正文",
      "publish_ready": false
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["douyin"],
        platform_packaging=str(packaging_json),
        enforce_gate=False,
    )

    assert report["checked"] is True
    assert report["gate_enforced"] is False
    assert report["status"] == "report_only"
    assert report["reported_failures"] == ["发布文案未就绪：douyin"]
    assert report["failures"] == []


def test_evaluate_packaging_preflight_preserves_manual_handoff_platform(tmp_path: Path) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "wechat-channels": {
      "manual_handoff_only": true,
      "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
      "publish_ready": false
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["wechat-channels"],
        platform_packaging=str(packaging_json),
    )

    assert report["checked"] is True
    assert report["status"] == "manual_handoff"
    assert report["failures"] == []
    assert report["platform_checks"]["wechat-channels"]["status"] == "manual_handoff"
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]


def test_evaluate_packaging_preflight_treats_object_shape_ready_entry_without_publish_ready_as_ready(tmp_path: Path) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "douyin": {
      "titles": ["真实标题"],
      "description": "真实正文",
      "live_publish_preflight": {
        "status": "ready",
        "missing_required_surfaces": []
      }
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["douyin"],
        platform_packaging=str(packaging_json),
    )

    assert report["checked"] is True
    assert report["status"] == "passed"
    assert report["failures"] == []
    assert report["platform_checks"]["douyin"]["status"] == "ready"


def test_evaluate_packaging_preflight_allows_collection_only_override_without_metadata_block(tmp_path: Path) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "kuaishou": {
      "description": "快手正文",
      "tags": ["EDC", "开箱"],
      "cover_path": "cover.jpg",
      "platform_specific_overrides": {
        "collection_policy": "skip",
        "skip_collection_select": true
      }
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["kuaishou"],
        platform_packaging=str(packaging_json),
    )

    assert report["checked"] is True
    assert report["status"] == "passed"
    assert report["failures"] == []
    assert report["platform_checks"]["kuaishou"]["status"] == "ready"


def test_evaluate_packaging_preflight_blocks_object_shape_entry_when_publish_ready_true_but_preflight_blocked(
    tmp_path: Path,
) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "douyin": {
      "titles": ["真实标题"],
      "description": "真实正文",
      "publish_ready": true,
      "live_publish_preflight": {
        "status": "blocked",
        "missing_required_surfaces": ["cover"]
      }
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["douyin"],
        platform_packaging=str(packaging_json),
    )

    assert report["checked"] is True
    assert report["status"] == "failed"
    assert report["platform_checks"]["douyin"]["status"] == "blocked"
    assert report["failures"] == ["douyin: 缺少关键参数面 cover"]


def test_evaluate_packaging_preflight_derives_blocking_reasons_from_preflight_when_missing(tmp_path: Path) -> None:
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platforms": {
    "douyin": {
      "titles": ["真实标题"],
      "description": "真实正文",
      "publish_ready": true,
      "blocking_reasons": [],
      "live_publish_preflight": {
        "status": "blocked",
        "missing_required_surfaces": ["cover"]
      }
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["douyin"],
        platform_packaging=str(packaging_json),
    )

    assert report["checked"] is True
    assert report["status"] == "failed"
    assert report["platform_checks"]["douyin"]["status"] == "blocked"
    assert report["platform_checks"]["douyin"]["blocking_reasons"] == ["缺少发布前必要页面能力：cover"]
    assert report["failures"] == ["douyin: 缺少关键参数面 cover"]


def test_evaluate_packaging_preflight_backfills_missing_requested_platform_from_material_when_sibling_packaging_is_partial(
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
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
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

    report = preflight._evaluate_packaging_preflight(
        platforms=["bilibili"],
        material_json=str(material_json),
    )

    assert report["checked"] is True
    assert report["status"] == "passed"
    assert report["source"] == "platform_packaging+material_json"
    assert report["platform_checks"]["bilibili"]["status"] == "ready"
    assert report["failures"] == []


def test_evaluate_packaging_preflight_reports_platform_scope_mismatch_for_uncovered_requested_platform(
    tmp_path: Path,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "douyin",
      "primary_title": "抖音标题",
      "body": "抖音正文",
      "tags": ["EDC"]
    }
  ],
  "material_contract": {
    "platform_scope": {
      "requested_platforms": ["douyin"],
      "covered_platforms": ["douyin"],
      "missing_requested_platforms": []
    }
  }
}""",
        encoding="utf-8",
    )

    report = preflight._evaluate_packaging_preflight(
        platforms=["bilibili"],
        material_json=str(material_json),
    )

    assert report["checked"] is True
    assert report["status"] == "failed"
    assert report["platform_checks"]["bilibili"]["status"] == "missing"
    assert report["platform_checks"]["bilibili"]["message"] == "该平台不在本期物料合同覆盖范围内。当前仅覆盖平台 -> douyin"
    assert report["failures"] == ["发布范围不匹配：bilibili 不在本期物料生成范围内。当前仅覆盖平台 -> douyin"]


def test_resolve_requested_platforms_prefers_material_scope_over_static_defaults(tmp_path: Path) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "platforms": [
    {
      "key": "bilibili",
      "primary_title": "B站标题",
      "body": "B站正文",
      "tags": ["EDC"]
    },
    {
      "key": "xiaohongshu",
      "primary_title": "小红书标题",
      "body": "小红书正文",
      "tags": ["EDC"]
    }
  ],
  "material_contract": {
    "platform_scope": {
      "requested_platforms": ["bilibili", "xiaohongshu"],
      "covered_platforms": ["bilibili", "xiaohongshu"],
      "missing_requested_platforms": []
    }
  }
}""",
        encoding="utf-8",
    )

    resolved = preflight._resolve_requested_platforms([], material_json=str(material_json))

    assert resolved == ["bilibili", "xiaohongshu"]


def test_resolve_requested_platforms_keeps_explicit_cli_platforms(tmp_path: Path) -> None:
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

    resolved = preflight._resolve_requested_platforms(["douyin"], material_json=str(material_json))

    assert resolved == ["douyin"]


def test_build_preflight_publication_verification_surfaces_probe_gate_blocked_recommendation() -> None:
    result = {
        "failures": ["bilibili: 实际发布页缺少关键参数面 cover, category, schedule"],
        "agent_ready": {
            "ready": True,
            "code": "ready",
            "message": "",
            "health": {
                "creator_sessions": {
                    "bilibili": {
                        "visual_evidence": {
                            "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260602/bilibili/session.png",
                            "capture_type": "screenshot",
                            "phase": "creator_session_probe",
                        }
                    }
                }
            },
        },
        "probe_inventory": {
            "checked": True,
            "status": "partial",
            "platforms": {
                "bilibili": {
                    "visual_evidence": {
                        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260602/bilibili/probe.png",
                        "capture_type": "screenshot",
                        "phase": "probe_inventory",
                    }
                }
            },
        },
        "packaging": {
            "checked": True,
            "status": "passed",
            "platform_checks": {
                "bilibili": {"status": "ready", "message": "发布物料合同就绪。"}
            },
        },
        "cdp": {"connected": True, "platform_checks": {"bilibili": {"status": "found"}}},
    }

    verification = preflight._build_preflight_publication_verification(
        result,
        requested_platforms=["bilibili"],
        require_tabs=True,
    )
    mitigation = preflight._build_preflight_mitigation(
        result["failures"],
        verification["recommendations"],
        summary_status=verification["summary_status"],
    )

    assert verification["summary_status"] == "failed"
    assert verification["recommendations"] == [
        {
            "platform": "bilibili",
            "issue": "probe_gate_blocked",
            "operations": ["inspect_probe_visual_evidence", "repair_live_publish_preflight", "rerun_preflight"],
            "auto_remediable": True,
        }
    ]
    assert verification["creator_session_visual_evidence_by_platform"]["bilibili"]["phase"] == "creator_session_probe"
    assert verification["probe_inventory_visual_evidence_by_platform"]["bilibili"]["phase"] == "probe_inventory"
    assert mitigation["steps"] == [
        "检测到实际发布页缺少关键参数面，请结合截图证据修复 live_publish_preflight 或页面能力后再重跑 preflight。"
    ]
    assert mitigation["playbook"]["probe_gate_blocked"] == [
        "inspect_probe_visual_evidence",
        "repair_live_publish_preflight",
        "rerun_preflight",
    ]


def test_build_preflight_publication_verification_fails_when_probe_inventory_fetch_failed() -> None:
    result = {
        "failures": ["browser-agent probe inventory 拉取失败：probe timeout"],
        "agent_ready": {"ready": True, "code": "ready", "message": "", "health": {}},
        "probe_inventory": {
            "checked": True,
            "status": "probe_failed",
            "platforms": {},
            "failures": ["browser-agent probe inventory 拉取失败：probe timeout"],
        },
        "packaging": {
            "checked": True,
            "status": "report_only",
            "gate_enforced": False,
            "platform_checks": {"xiaohongshu": {"status": "blocked", "message": "platform-packaging 标记为未就绪。"}},
            "failures": [],
            "reported_failures": ["发布文案未就绪：xiaohongshu"],
        },
        "cdp": {"connected": True, "platform_checks": {"xiaohongshu": {"status": "found"}}},
    }

    verification = preflight._build_preflight_publication_verification(
        result,
        requested_platforms=["xiaohongshu"],
        require_tabs=True,
    )

    assert verification["summary_status"] == "failed"
    assert verification["recommendations"] == [
        {
            "platform": "",
            "issue": "probe_inventory_failed",
            "operations": ["inspect_probe_visual_evidence", "restore_browser_agent", "rerun_preflight"],
            "auto_remediable": True,
        }
    ]
