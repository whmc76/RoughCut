from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from roughcut.config import get_settings  # noqa: E402
from roughcut.db.models import Job  # noqa: E402
from roughcut.db.session import Base  # noqa: E402
from roughcut.publication_packaging import (  # noqa: E402
    filter_publication_packaging_platforms,
    load_json_payload,
    load_publication_packaging_payload,
    normalize_publication_packaging_payload,
    publication_packaging_payload_publish_ready,
)
from roughcut.publication import (  # noqa: E402
    build_publication_plan,
    check_publication_browser_agent_ready,
    list_publication_attempts,
    publication_plan_is_publishable,
    publication_plan_status,
    run_publication_worker_once,
    submit_publication_attempts,
)


class _FakeBrowserAgentResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingBrowserAgentClient:
    def __init__(self, status: str) -> None:
        self.status = status
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeBrowserAgentResponse:
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _FakeBrowserAgentResponse(
            {
                "task": {
                    "task_id": json["task_id"],
                    "status": self.status,
                    "execution_id": "minimax-cdp-smoke-run",
                    "result": {
                        "post_id": "minimax-cdp-smoke",
                        "publication_audit": {"verified": True, "required_unverified": []},
                    },
                }
            }
        )

    async def get(self, url: str, *, headers: dict[str, str]) -> _FakeBrowserAgentResponse:
        self.gets.append({"url": url, "headers": headers})
        task_id = url.rsplit("/", 1)[-1]
        return _FakeBrowserAgentResponse(
            {
                "task": {
                    "task_id": task_id,
                    "status": self.status,
                    "execution_id": "minimax-cdp-smoke-run",
                    "result": {
                        "post_id": "minimax-cdp-smoke",
                        "publication_audit": {"verified": True, "required_unverified": []},
                    },
                }
            }
        )


def _now_stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")


def _backend_smoke_status(
    *,
    plan: dict[str, Any],
    submit_result: dict[str, Any],
    posted_tasks: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    platform_count: int,
    fake_status: str,
) -> str:
    plan_status = publication_plan_status(plan)
    if plan_status == "manual_handoff":
        return "manual_handoff"
    if plan_status != "ready" or plan.get("publish_ready") is False or not bool(plan.get("targets")):
        return "blocked"
    expected_target_count = len(plan.get("targets") or []) or platform_count
    if (
        len(submit_result.get("created_attempts") or []) == expected_target_count
        and len(posted_tasks) == expected_target_count
        and len(attempts) == expected_target_count
        and all(str(attempt.get("status")) == fake_status for attempt in attempts)
    ):
        return "passed"
    return "failed"


def _normalize_publication_adapter(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_")


def _normalize_publication_execution_mode(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_") or "browser_agent"


def _normalize_platform_packaging_payload(raw_packaging: Any, *, platforms: list[str]) -> dict[str, Any] | None:
    normalized = normalize_publication_packaging_payload(raw_packaging)
    return filter_publication_packaging_platforms(normalized, platforms=platforms)


def _resolve_platform_packaging(
    *,
    platforms: list[str],
    material_json: str = "",
    platform_packaging: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    normalized_packaging, packaging_sources = load_publication_packaging_payload(
        material_json=material_json,
        platform_packaging=platform_packaging,
        platforms=platforms,
    )
    normalized_packaging = filter_publication_packaging_platforms(normalized_packaging, platforms=platforms)
    if normalized_packaging is None:
        normalized_packaging = _platform_packaging(platforms)
        packaging_sources = {
            "source": "fixture",
            "material_json_path": packaging_sources.get("material_json_path", ""),
            "platform_packaging_path": packaging_sources.get("platform_packaging_path", ""),
        }
    return normalized_packaging, packaging_sources


def _platform_packaging(platforms: list[str]) -> dict[str, Any]:
    packaging = {
        "copy_style": "m27_claim_grounded",
        "publish_ready": True,
        "claim_ledger": [
            {
                "id": "c1",
                "claim_type": "identity",
                "text": "样片展示一件桌面数码配件。",
                "evidence": "smoke fixture",
            },
            {
                "id": "c2",
                "claim_type": "subjective_opinion",
                "text": "可以表达手感和质感体验。",
                "evidence": "smoke fixture",
            },
        ],
        "platforms": {
            platform: {
                "titles": [f"{platform} MiniMax 发布链路烟测"],
                "description": "基于证据闭环生成的 MiniMax M2.7 发布物料，用于验证 CDP 发布任务合同。",
                "tags": ["MiniMax", "RoughCut", "发布测试"],
                "claim_refs": ["c1", "c2"],
                "publish_ready": True,
            }
            for platform in platforms
        },
    }
    packaging["publish_ready"] = publication_packaging_payload_publish_ready(packaging)
    if packaging["publish_ready"]:
        packaging["blocking_reasons"] = []
    return packaging


def _creator_profile(
    platforms: list[str],
    *,
    publication_adapter: str,
    execution_mode: str,
) -> dict[str, Any]:
    normalized_adapter = _normalize_publication_adapter(publication_adapter)
    normalized_execution_mode = _normalize_publication_execution_mode(execution_mode)
    return {
        "id": "minimax-cdp-smoke-profile",
        "display_name": "MiniMax CDP Smoke",
        "creator_profile": {
            "publishing": {
                "platform_credentials": [
                    {
                        "platform": platform,
                        "account_label": f"{platform}-smoke",
                        "credential_ref": f"browser-agent:smoke:{platform}",
                        "status": "logged_in",
                        "enabled": True,
                        "adapter": normalized_adapter,
                        "execution_mode": normalized_execution_mode,
                    }
                    for platform in platforms
                ]
            }
        },
    }


async def _run_backend_contract_smoke(
    platforms: list[str],
    report_dir: Path,
    fake_status: str,
    *,
    publication_adapter: str,
    execution_mode: str,
    material_json: str = "",
    platform_packaging: str = "",
) -> dict[str, Any]:
    media_path = report_dir / "minimax-cdp-smoke.mp4"
    media_path.write_bytes(b"roughcut minimax cdp smoke video placeholder")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    fake_client = _RecordingBrowserAgentClient(fake_status)
    packaging_payload, packaging_sources = _resolve_platform_packaging(
        platforms=platforms,
        material_json=material_json,
        platform_packaging=platform_packaging,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                source_path=str(media_path),
                source_name=media_path.name,
                status="done",
                workflow_template="intelligent_publish",
            )
            session.add(job)
            await session.flush()
            plan = build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging=packaging_payload,
                creator_profile=_creator_profile(
                    platforms,
                    publication_adapter=publication_adapter,
                    execution_mode=execution_mode,
                ),
                requested_platforms=platforms,
                platform_options={
                    platform: {
                        "visibility_or_publish_mode": "draft",
                        "live_publish_preflight": {
                            "status": "passed",
                            "missing_required_surfaces": [],
                            "summary": "smoke preflight fixture",
                        },
                    }
                    for platform in platforms
                },
                existing_attempts=[],
            )
            submit_result = await submit_publication_attempts(session, plan)
            worker_result = await run_publication_worker_once(
                session,
                browser_agent_base_url="http://browser-agent.local",
                auth_token="<test-token>",
                worker_id="minimax-cdp-smoke",
                limit=max(1, len(platforms)),
                http_client=fake_client,
            )
            attempts = await list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    posted_tasks = [item["json"] for item in fake_client.posts]
    smoke_status = _backend_smoke_status(
        plan=plan,
        submit_result=submit_result,
        posted_tasks=posted_tasks,
        attempts=attempts,
        platform_count=len(platforms),
        fake_status=fake_status,
    )
    return {
        "status": smoke_status,
        "plan_status": publication_plan_status(plan),
        "plan_publish_ready": publication_plan_is_publishable(plan),
        "plan_manual_handoff_ready": publication_plan_status(plan) == "manual_handoff",
        "plan_blocked_reasons": [str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip()],
        "plan_targets": [target.get("platform") for target in plan.get("targets") or []],
        "platform_packaging_source": packaging_sources.get("source"),
        "platform_packaging_path": packaging_sources.get("platform_packaging_path"),
        "material_json_path": packaging_sources.get("material_json_path"),
        "requested_platform_count": len(platforms),
        "expected_target_count": len(plan.get("targets") or []),
        "created_attempts": len(submit_result.get("created_attempts") or []),
        "worker_result": worker_result,
        "attempt_statuses": {attempt.get("platform"): attempt.get("status") for attempt in attempts},
        "task_contracts": [
            {
                "platform": task.get("platform"),
                "profile_id": task.get("profile_id"),
                "title": ((task.get("content") or {}).get("title") or "")[:120],
                "local_file_count": ((task.get("content") or {}).get("publish_media_source") or {}).get("local_file_count"),
                "validation_contract": (task.get("content") or {}).get("validation_contract"),
                "visibility_or_publish_mode": (task.get("content") or {}).get("visibility_or_publish_mode"),
            }
            for task in posted_tasks
        ],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test MiniMax-routed RoughCut publication/CDP contracts.")
    parser.add_argument("--platform", action="append", dest="platforms", help="Target platform; repeatable.")
    parser.add_argument("--report-dir", default=str(REPO_ROOT / "output" / "test" / "minimax-publication-cdp"))
    parser.add_argument("--publication-adapter", default="browser_agent", help="publication adapter for smoke credentials.")
    parser.add_argument("--execution-mode", default="browser_agent", help="execution mode for fake smoke attempts.")
    parser.add_argument("--fake-agent-status", default="draft_created", choices=["draft_created", "published", "scheduled_pending"])
    parser.add_argument("--material-json", default="", help="可选：smart-copy.json 路径；用于从 sibling 推导真实 platform-packaging。")
    parser.add_argument("--platform-packaging", default="", help="可选：真实 platform-packaging.json 路径；优先于 fixture。")
    args = parser.parse_args()

    platforms = args.platforms or ["douyin"]
    report_dir = Path(args.report_dir) / _now_stamp()
    report_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    live_ready = await check_publication_browser_agent_ready(
        browser_agent_base_url=str(getattr(settings, "publication_browser_agent_base_url", "") or ""),
        auth_token=str(getattr(settings, "publication_browser_agent_auth_token", "") or ""),
        target_platforms=platforms,
        target_profile_ids=[f"browser-agent:chrome:minimax-cdp-smoke-profile:{platform}" for platform in platforms],
        request_timeout_sec=5,
    )
    backend_smoke = await _run_backend_contract_smoke(
        platforms,
        report_dir,
        args.fake_agent_status,
        publication_adapter=args.publication_adapter,
        execution_mode=args.execution_mode,
        material_json=args.material_json,
        platform_packaging=args.platform_packaging,
    )
    report = {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "status": "passed" if backend_smoke.get("status") == "passed" else "failed",
        "minimax_route": {
            "reasoning_provider": getattr(settings, "reasoning_provider", ""),
            "reasoning_model": getattr(settings, "reasoning_model", ""),
            "hybrid_analysis_provider": getattr(settings, "hybrid_analysis_provider", ""),
            "hybrid_analysis_model": getattr(settings, "hybrid_analysis_model", ""),
            "multimodal_fallback_provider": getattr(settings, "multimodal_fallback_provider", ""),
            "multimodal_fallback_model": getattr(settings, "multimodal_fallback_model", ""),
            "search_provider": getattr(settings, "search_provider", ""),
            "search_fallback_provider": getattr(settings, "search_fallback_provider", ""),
        },
        "live_cdp_publication_readiness": {
            "ready": bool(live_ready.get("ready")),
            "code": live_ready.get("code"),
            "message": live_ready.get("message"),
            "health": live_ready.get("health") or {},
        },
        "backend_publication_contract_smoke": backend_smoke,
        "note": (
            "backend_publication_contract_smoke uses a recording fake browser-agent and never clicks a real platform. "
            "live_cdp_publication_readiness is the real browser-agent/CDP gate."
        ),
    }
    report_path = report_dir / "minimax_publication_cdp_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
