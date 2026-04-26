from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import PublicationAttempt, PublicationAttemptRun

CANONICAL_PUBLICATION_ADAPTER = "browser_agent"
BROWSER_AGENT_PUBLICATION_RUN_CONTRACT = "browser_agent_publication_v1"
PUBLISHABLE_CREDENTIAL_STATUSES = {"logged_in", "available", "verified"}
PUBLICATION_ACTIVE_STATUSES = {"queued", "claimed", "submitted", "processing", "scheduled_pending"}
PUBLICATION_RECONCILE_STATUSES = {"submitted", "processing", "scheduled_pending"}
PUBLICATION_TERMINAL_STATUSES = {"published", "draft_created", "failed", "needs_human", "cancelled"}
PUBLICATION_SUCCESS_STATUSES = {"published", "draft_created", "scheduled_pending"}
BROWSER_AGENT_RETRYABLE_STATUSES = {"network_error", "rate_limited", "upload_failed"}
BROWSER_AGENT_HUMAN_STATUSES = {"auth_expired", "captcha_required", "human_confirm", "needs_human"}
BROWSER_AGENT_FAILED_STATUSES = {
    "content_rejected",
    "dom_changed",
    "failed",
    "failed_permanent",
    "partial_failed",
    "unknown",
}

SUPPORTED_PUBLICATION_PLATFORMS: dict[str, dict[str, str]] = {
    "douyin": {"label": "抖音", "kind": "video"},
    "xiaohongshu": {"label": "小红书", "kind": "video"},
    "bilibili": {"label": "B站", "kind": "video"},
    "wechat-channels": {"label": "视频号", "kind": "video"},
    "toutiao": {"label": "头条号", "kind": "video"},
}

_PLATFORM_ALIASES = {
    "抖音": "douyin",
    "douyin": "douyin",
    "小红书": "xiaohongshu",
    "xiaohongshu": "xiaohongshu",
    "rednote": "xiaohongshu",
    "b站": "bilibili",
    "哔哩哔哩": "bilibili",
    "bilibili": "bilibili",
    "wechat-channels": "wechat-channels",
    "wechat_channels": "wechat-channels",
    "视频号": "wechat-channels",
    "微信视频号": "wechat-channels",
    "头条": "toutiao",
    "头条号": "toutiao",
    "toutiao": "toutiao",
}


def normalize_publication_platform(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text).lower().replace("_", "-")
    return _PLATFORM_ALIASES.get(compact) or (compact if compact in SUPPORTED_PUBLICATION_PLATFORMS else None)


def platform_label(platform: str) -> str:
    return SUPPORTED_PUBLICATION_PLATFORMS.get(platform, {}).get("label") or platform


def normalize_publication_credentials(value: Any) -> list[dict[str, Any]]:
    raw_items = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        platform = normalize_publication_platform(item.get("platform"))
        if not platform:
            continue
        credential_ref = str(item.get("credential_ref") or item.get("browser_profile") or "").strip()
        account_label = str(item.get("account_label") or item.get("account") or "").strip()
        status = str(item.get("status") or "unverified").strip().lower().replace("-", "_")
        adapter = str(item.get("adapter") or CANONICAL_PUBLICATION_ADAPTER).strip().lower().replace("-", "_")
        enabled = bool(item.get("enabled", True))
        key = (platform, credential_ref or account_label)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "platform": platform,
                "platform_label": platform_label(platform),
                "account_label": account_label or platform_label(platform),
                "credential_ref": credential_ref,
                "status": status,
                "enabled": enabled,
                "adapter": adapter,
                "verified_at": str(item.get("verified_at") or "").strip() or None,
                "notes": str(item.get("notes") or "").strip() or None,
                "last_error": str(item.get("last_error") or "").strip() or None,
            }
        )
    return normalized[:16]


def active_publication_credentials(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    creator_profile = profile.get("creator_profile") if isinstance(profile, dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile, dict) else {}
    credentials = normalize_publication_credentials(
        publishing.get("platform_credentials") if isinstance(publishing, dict) else []
    )
    return [
        item
        for item in credentials
        if item["enabled"]
        and item["adapter"] == CANONICAL_PUBLICATION_ADAPTER
        and item["status"] in PUBLISHABLE_CREDENTIAL_STATUSES
    ]


def build_publication_plan(
    *,
    job: Any,
    render_output: Any | None,
    platform_packaging: dict[str, Any] | None,
    creator_profile: dict[str, Any] | None,
    requested_platforms: list[str] | None = None,
    platform_options: dict[str, Any] | None = None,
    existing_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocked_reasons: list[str] = []
    warnings: list[str] = []
    if str(getattr(job, "status", "") or "") != "done":
        blocked_reasons.append("任务尚未完成，不能发布。")

    media_path = _resolve_render_media_path(render_output)
    if media_path is None:
        blocked_reasons.append("缺少本地成片文件，browser-agent 不能上传 remote-only media。")

    packages = _normalize_platform_packages(platform_packaging)
    if not packages:
        blocked_reasons.append("缺少多平台发布文案包，请先完成 platform_package。")

    credentials = active_publication_credentials(creator_profile)
    if not credentials:
        blocked_reasons.append("创作者档案没有可发布的 browser-agent 登录凭据绑定。")

    requested = {
        platform
        for platform in (normalize_publication_platform(item) for item in (requested_platforms or []))
        if platform
    }
    credential_by_platform = {item["platform"]: item for item in credentials}
    options_by_platform = _normalize_publication_platform_options(platform_options)
    target_platforms = sorted((requested or set(credential_by_platform)) & set(packages), key=_platform_sort_key)
    targets: list[dict[str, Any]] = []
    for platform in target_platforms:
        credential = credential_by_platform.get(platform)
        package = packages.get(platform) or {}
        publish_options = options_by_platform.get(platform, {})
        if not credential:
            warnings.append(f"{platform_label(platform)} 没有可用登录凭据，已跳过。")
            continue
        if not _package_has_publish_copy(package):
            warnings.append(f"{platform_label(platform)} 文案包为空，已跳过。")
            continue
        targets.append(
            {
                "platform": platform,
                "platform_label": platform_label(platform),
                "credential_id": credential["id"],
                "credential_ref": credential["credential_ref"],
                "browser_profile_id": credential["credential_ref"] or credential["account_label"] or platform,
                "account_label": credential["account_label"],
                "adapter": CANONICAL_PUBLICATION_ADAPTER,
                "content_kind": "video",
                "title": _package_primary_title(package),
                "body": str(package.get("description") or package.get("body") or "").strip(),
                "tags": [str(item).strip() for item in (package.get("tags") or []) if str(item).strip()],
                "category": publish_options.get("category"),
                "collection": publish_options.get("collection"),
                "visibility_or_publish_mode": publish_options.get("visibility_or_publish_mode"),
                "scheduled_publish_at": publish_options.get("scheduled_publish_at"),
                "platform_specific_overrides": publish_options.get("platform_specific_overrides") or {},
                "status": "ready",
            }
        )

    if credentials and packages and not targets:
        blocked_reasons.append("当前创作者凭据与文案包平台没有交集。")

    return {
        "job_id": str(getattr(job, "id", "")),
        "status": "ready" if not blocked_reasons and targets else "blocked",
        "publish_ready": not blocked_reasons and bool(targets),
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
        "adapter": CANONICAL_PUBLICATION_ADAPTER,
        "content_kind": "video",
        "publication_guard": {
            "ready": not blocked_reasons and bool(targets),
            "review_gate_blocked": False,
            "formal_plan": {
                "ready": str(getattr(job, "status", "") or "") == "done",
                "reasons": [] if str(getattr(job, "status", "") or "") == "done" else ["job_not_done"],
            },
            "release_payload": {
                "ready": bool(media_path and packages),
                "reasons": [] if media_path and packages else ["local_media_or_platform_package_missing"],
            },
        },
        "creator_profile_id": str((creator_profile or {}).get("id") or ""),
        "creator_profile_name": str((creator_profile or {}).get("display_name") or ""),
        "media_path": str(media_path) if media_path else None,
        "targets": targets,
        "existing_attempts": list(existing_attempts or [])[:20],
    }


async def submit_publication_attempts(session: AsyncSession, plan: dict[str, Any]) -> dict[str, Any]:
    if not plan.get("publish_ready"):
        return {**plan, "created_attempts": []}

    created: list[dict[str, Any]] = []
    fingerprint_result = await session.execute(
        select(PublicationAttempt.semantic_fingerprint).where(
            PublicationAttempt.status.notin_(["failed", "cancelled"])
        )
    )
    existing_fingerprints = {str(item or "") for item in fingerprint_result.scalars().all() if str(item or "")}
    for target in plan.get("targets") or []:
        request_payload = _build_request_payload(plan=plan, target=target)
        fingerprint = _semantic_fingerprint(
            job_id=str(plan.get("job_id") or ""),
            platform=str(target.get("platform") or ""),
            title=str(target.get("title") or ""),
            body=str(target.get("body") or ""),
            media_path=str(plan.get("media_path") or ""),
        )
        if fingerprint in existing_fingerprints:
            continue
        attempt_id = uuid.uuid4().hex
        attempt = PublicationAttempt(
            id=attempt_id,
            content_id=str(plan.get("job_id") or ""),
            job_id=uuid.UUID(str(plan.get("job_id") or "")),
            creator_profile_id=str(plan.get("creator_profile_id") or ""),
            creator_profile_name=str(plan.get("creator_profile_name") or ""),
            platform=str(target.get("platform") or ""),
            platform_label=str(target.get("platform_label") or ""),
            account_label=str(target.get("account_label") or ""),
            credential_id=str(target.get("credential_id") or ""),
            adapter=CANONICAL_PUBLICATION_ADAPTER,
            status="queued",
            run_status="awaiting_browser_agent",
            attempt_number=1,
            retry_count=0,
            max_retries=3,
            execution_mode="browser_agent",
            content_kind="video",
            request_payload=request_payload,
            response_payload=None,
            scheduled_at=_parse_datetime(target.get("scheduled_publish_at")),
            semantic_fingerprint=fingerprint,
            idempotency_key=f"{plan.get('job_id')}:{target.get('platform')}:{fingerprint[:12]}",
            operator_summary=(
                "已创建 browser-agent 预约发布任务，等待运行器认领。"
                if target.get("scheduled_publish_at")
                else "已创建 browser-agent 发布任务，等待运行器认领。"
            ),
        )
        run = PublicationAttemptRun(
            attempt_id=attempt_id,
            content_id=str(plan.get("job_id") or ""),
            platform=str(target.get("platform") or ""),
            adapter=CANONICAL_PUBLICATION_ADAPTER,
            execution_mode="browser_agent",
            content_kind="video",
            consumer_id="",
            attempt_number=1,
            status="queued",
            phase="materialized",
            metadata_json={
                "contract": BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
                "reconcileMode": "browser_agent_task_poll",
            },
        )
        session.add(attempt)
        session.add(run)
        await session.flush()
        created.append(serialize_publication_attempt(attempt, runs=[run]))
        existing_fingerprints.add(fingerprint)
    existing_attempts = await list_publication_attempts(session, job_id=str(plan.get("job_id") or ""))
    return {
        **plan,
        "status": "queued" if created else plan.get("status"),
        "created_attempts": created,
        "existing_attempts": existing_attempts[:20],
    }


async def claim_publication_attempts(
    session: AsyncSession,
    *,
    limit: int = 5,
    worker_id: str = "",
    lease_seconds: int = 300,
) -> list[PublicationAttempt]:
    now = _utc_now()
    stmt = (
        select(PublicationAttempt)
        .where(
            PublicationAttempt.adapter == CANONICAL_PUBLICATION_ADAPTER,
            PublicationAttempt.status == "queued",
            or_(PublicationAttempt.next_retry_at.is_(None), PublicationAttempt.next_retry_at <= now),
        )
        .order_by(PublicationAttempt.created_at.asc(), PublicationAttempt.id.asc())
        .limit(max(1, int(limit or 1)))
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    attempts = result.scalars().all()
    claimed: list[PublicationAttempt] = []
    for attempt in attempts:
        attempt.status = "claimed"
        attempt.run_status = "claimed"
        attempt.error_code = None
        attempt.error_message = None
        attempt.operator_summary = "发布任务已被 worker 认领，准备提交 browser-agent。"
        run = PublicationAttemptRun(
            attempt_id=attempt.id,
            content_id=attempt.content_id,
            platform=attempt.platform,
            adapter=CANONICAL_PUBLICATION_ADAPTER,
            execution_mode="browser_agent",
            content_kind=attempt.content_kind or "video",
            consumer_id=str(worker_id or ""),
            attempt_number=max(1, int(attempt.attempt_number or 1)),
            status="claimed",
            phase="claim",
            started_at=now,
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=max(30, int(lease_seconds or 300))),
            metadata_json={
                "contract": BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
                "reconcileMode": "browser_agent_task_poll",
            },
        )
        session.add(run)
        claimed.append(attempt)
    if claimed:
        await session.flush()
    return claimed


async def submit_publication_attempt_to_browser_agent(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    run = await _latest_publication_run(session, attempt.id)
    try:
        task_payload = build_browser_agent_task_payload_from_attempt(attempt)
    except ValueError as exc:
        _mark_publication_attempt_failed(
            attempt,
            run,
            code="publication_payload_invalid",
            message=str(exc),
            retryable=False,
        )
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}

    try:
        response_payload = await _browser_agent_request_json(
            "POST",
            "/tasks",
            base_url=browser_agent_base_url,
            auth_token=auth_token,
            json_payload=task_payload,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    except Exception as exc:
        _mark_publication_attempt_failed(
            attempt,
            run,
            code="browser_agent_submit_failed",
            message=str(exc),
            retryable=True,
        )
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}

    task = _extract_browser_agent_task(response_payload)
    provider_task_id = str(task.get("task_id") or task.get("id") or attempt.id).strip() or attempt.id
    now = _utc_now()
    attempt.provider_task_id = provider_task_id
    attempt.provider_execution_id = str(task.get("execution_id") or task.get("run_id") or "").strip() or None
    attempt.provider_status = str(task.get("status") or "submitted").strip() or "submitted"
    attempt.response_payload = response_payload
    attempt.status = "submitted"
    attempt.run_status = "submitted"
    attempt.submitted_at = now
    attempt.next_retry_at = None
    attempt.operator_summary = "已提交 browser-agent，等待平台侧执行结果。"
    if run is not None:
        run.status = "submitted"
        run.phase = "submitted"
        run.heartbeat_at = now
        run.provider_task_id = provider_task_id
        run.provider_execution_id = attempt.provider_execution_id
        run.provider_status = attempt.provider_status
        run.result_json = response_payload
    _apply_browser_agent_task_state(attempt, run, task, response_payload=response_payload)
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "provider_task_id": provider_task_id}


async def reconcile_publication_attempt_with_browser_agent(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    provider_task_id = str(attempt.provider_task_id or attempt.id).strip()
    run = await _latest_publication_run(session, attempt.id)
    try:
        response_payload = await _browser_agent_request_json(
            "GET",
            f"/tasks/{provider_task_id}",
            base_url=browser_agent_base_url,
            auth_token=auth_token,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    except Exception as exc:
        if run is not None:
            run.status = "poll_failed"
            run.phase = "reconcile"
            run.heartbeat_at = _utc_now()
            run.error_message = str(exc)
        attempt.run_status = "poll_failed"
        attempt.operator_summary = f"browser-agent 对账失败，等待下次轮询：{exc}"
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}
    task = _extract_browser_agent_task(response_payload)
    _apply_browser_agent_task_state(attempt, run, task, response_payload=response_payload)
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "provider_status": attempt.provider_status}


async def run_publication_worker_once(
    session: AsyncSession,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    worker_id: str = "",
    limit: int = 5,
    lease_seconds: int = 300,
    request_timeout_sec: int = 60,
    http_client: Any | None = None,
) -> dict[str, Any]:
    claimed = await claim_publication_attempts(
        session,
        limit=limit,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    submitted: list[dict[str, Any]] = []
    for attempt in claimed:
        submitted.append(
            await submit_publication_attempt_to_browser_agent(
                session,
                attempt,
                browser_agent_base_url=browser_agent_base_url,
                auth_token=auth_token,
                http_client=http_client,
                request_timeout_sec=request_timeout_sec,
            )
        )

    reconcile_stmt = (
        select(PublicationAttempt)
        .where(
            PublicationAttempt.adapter == CANONICAL_PUBLICATION_ADAPTER,
            PublicationAttempt.status.in_(PUBLICATION_RECONCILE_STATUSES),
        )
        .order_by(PublicationAttempt.updated_at.asc(), PublicationAttempt.created_at.asc())
        .limit(max(1, int(limit or 1)))
    )
    reconcile_result = await session.execute(reconcile_stmt)
    reconcile_attempts = [attempt for attempt in reconcile_result.scalars().all() if attempt.id not in {a.id for a in claimed}]
    reconciled: list[dict[str, Any]] = []
    for attempt in reconcile_attempts:
        reconciled.append(
            await reconcile_publication_attempt_with_browser_agent(
                session,
                attempt,
                browser_agent_base_url=browser_agent_base_url,
                auth_token=auth_token,
                http_client=http_client,
                request_timeout_sec=request_timeout_sec,
            )
        )

    active_result = await session.execute(
        select(PublicationAttempt.id).where(
            PublicationAttempt.adapter == CANONICAL_PUBLICATION_ADAPTER,
            PublicationAttempt.status.in_(PUBLICATION_ACTIVE_STATUSES),
        )
    )
    active_count = len(active_result.scalars().all())
    return {
        "claimed": len(claimed),
        "submitted": submitted,
        "reconciled": reconciled,
        "active_count": active_count,
    }


async def list_publication_attempts(
    session: AsyncSession,
    *,
    job_id: str | None = None,
    creator_profile_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PublicationAttempt).order_by(PublicationAttempt.created_at.desc(), PublicationAttempt.id.desc())
    if job_id:
        stmt = stmt.where(PublicationAttempt.content_id == str(job_id))
    if creator_profile_id:
        stmt = stmt.where(PublicationAttempt.creator_profile_id == str(creator_profile_id))
    result = await session.execute(stmt)
    attempts = result.scalars().all()
    if not attempts:
        return []
    attempt_ids = [attempt.id for attempt in attempts]
    run_result = await session.execute(
        select(PublicationAttemptRun)
        .where(PublicationAttemptRun.attempt_id.in_(attempt_ids))
        .order_by(PublicationAttemptRun.created_at.desc(), PublicationAttemptRun.id.desc())
    )
    runs_by_attempt: dict[str, list[PublicationAttemptRun]] = {}
    for run in run_result.scalars().all():
        runs_by_attempt.setdefault(run.attempt_id, []).append(run)
    return [serialize_publication_attempt(attempt, runs=runs_by_attempt.get(attempt.id, [])) for attempt in attempts]


def serialize_publication_attempt(
    attempt: PublicationAttempt,
    *,
    runs: list[PublicationAttemptRun] | None = None,
) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "content_id": attempt.content_id,
        "job_id": str(attempt.job_id),
        "creator_profile_id": attempt.creator_profile_id,
        "creator_profile_name": attempt.creator_profile_name,
        "platform": attempt.platform,
        "platform_label": attempt.platform_label,
        "account_label": attempt.account_label,
        "credential_id": attempt.credential_id,
        "adapter": attempt.adapter,
        "status": attempt.status,
        "run_status": attempt.run_status,
        "attempt_number": attempt.attempt_number,
        "retry_count": attempt.retry_count,
        "max_retries": attempt.max_retries,
        "execution_mode": attempt.execution_mode,
        "content_kind": attempt.content_kind,
        "request_payload": attempt.request_payload or {},
        "response_payload": attempt.response_payload,
        "provider_task_id": attempt.provider_task_id,
        "provider_execution_id": attempt.provider_execution_id,
        "provider_status": attempt.provider_status,
        "external_receipt_id": attempt.external_receipt_id,
        "external_post_id": attempt.external_post_id,
        "external_url": attempt.external_url,
        "public_url": attempt.external_url,
        "scheduled_at": _iso_or_none(attempt.scheduled_at),
        "error_code": attempt.error_code,
        "error_message": attempt.error_message,
        "semantic_fingerprint": attempt.semantic_fingerprint,
        "idempotency_key": attempt.idempotency_key,
        "operator_summary": attempt.operator_summary,
        "created_at": _iso_or_none(attempt.created_at),
        "updated_at": _iso_or_none(attempt.updated_at),
        "runs": [serialize_publication_attempt_run(run) for run in (runs or [])],
    }


def serialize_publication_attempt_run(run: PublicationAttemptRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "attempt_id": run.attempt_id,
        "content_id": run.content_id,
        "platform": run.platform,
        "adapter": run.adapter,
        "execution_mode": run.execution_mode,
        "content_kind": run.content_kind,
        "consumer_id": run.consumer_id,
        "attempt_number": run.attempt_number,
        "status": run.status,
        "phase": run.phase,
        "started_at": _iso_or_none(run.started_at),
        "heartbeat_at": _iso_or_none(run.heartbeat_at),
        "lease_expires_at": _iso_or_none(run.lease_expires_at),
        "completed_at": _iso_or_none(run.completed_at),
        "provider_task_id": run.provider_task_id,
        "provider_execution_id": run.provider_execution_id,
        "provider_status": run.provider_status,
        "result": run.result_json,
        "error_message": run.error_message,
        "metadata": run.metadata_json or {},
        "created_at": _iso_or_none(run.created_at),
        "updated_at": _iso_or_none(run.updated_at),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_browser_agent_task_payload(attempt_id: str, *, plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    request_payload = _build_request_payload(plan=plan, target=target)
    media_items = list(request_payload.get("media_items") or [])
    return {
        "task_id": attempt_id,
        "platform": target.get("platform"),
        "profile_id": _sanitize_profile_id(
            (request_payload.get("metadata") or {}).get("browser_profile_id"),
            fallback=str(target.get("platform") or "default"),
        ),
        "content": {
            "title": request_payload.get("title") or "",
            "body": request_payload.get("body") or "",
            "content_kind": "video",
            "hashtags": request_payload.get("hashtags") or [],
            "display_hashtags": request_payload.get("display_hashtags") or [],
            "structured_tags": request_payload.get("structured_tags") or [],
            "native_topics": request_payload.get("native_topics") or [],
            "category": request_payload.get("category"),
            "collection": request_payload.get("collection"),
            "visibility_or_publish_mode": request_payload.get("visibility_or_publish_mode"),
            "scheduled_publish_at": request_payload.get("scheduled_publish_at"),
            "ui_control_semantics": request_payload.get("ui_control_semantics") or {},
            "platform_specific_overrides": request_payload.get("platform_specific_overrides") or {},
            "publication_capability": request_payload.get("publication_capability") or {},
            "validation_contract": request_payload.get("validation_contract") or BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
            "publish_media_source": {
                "provider": "local_file",
                "mode": "platform_native_upload",
                "requires_public_url": False,
                "local_file_count": sum(1 for item in media_items if str(item.get("local_path") or "").strip()),
            },
            "media_urls": [str(plan.get("media_path") or "")],
            "media_items": media_items,
            "metadata": request_payload.get("metadata") or {},
        },
    }


def build_browser_agent_task_payload_from_attempt(attempt: PublicationAttempt) -> dict[str, Any]:
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    media_items = [item for item in (request_payload.get("media_items") or []) if isinstance(item, dict)]
    local_media_items = [item for item in media_items if str(item.get("local_path") or "").strip()]
    if not local_media_items:
        raise ValueError("browser-agent 发布需要至少一个本地文件 media_items[].local_path")
    missing = [
        str(item.get("local_path") or "").strip()
        for item in local_media_items
        if not Path(str(item.get("local_path") or "").strip()).expanduser().is_file()
    ]
    if missing:
        raise ValueError(f"本地媒体文件不存在：{missing[0]}")
    metadata = request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {}
    return {
        "task_id": attempt.id,
        "platform": attempt.platform,
        "profile_id": _sanitize_profile_id(
            metadata.get("browser_profile_id"),
            fallback=attempt.platform or "default",
        ),
        "content": {
            "title": str(request_payload.get("title") or ""),
            "body": str(request_payload.get("body") or ""),
            "content_kind": str(request_payload.get("content_kind") or attempt.content_kind or "video"),
            "hashtags": list(request_payload.get("hashtags") or []),
            "display_hashtags": list(request_payload.get("display_hashtags") or []),
            "structured_tags": list(request_payload.get("structured_tags") or []),
            "native_topics": list(request_payload.get("native_topics") or []),
            "category": request_payload.get("category"),
            "collection": request_payload.get("collection"),
            "visibility_or_publish_mode": request_payload.get("visibility_or_publish_mode"),
            "scheduled_publish_at": request_payload.get("scheduled_publish_at"),
            "ui_control_semantics": request_payload.get("ui_control_semantics") or {},
            "platform_specific_overrides": request_payload.get("platform_specific_overrides") or {},
            "publication_capability": request_payload.get("publication_capability") or {},
            "validation_contract": request_payload.get("validation_contract") or BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
            "publish_media_source": {
                "provider": "local_file",
                "mode": "platform_native_upload",
                "requires_public_url": False,
                "local_file_count": len(local_media_items),
            },
            "media_urls": list(request_payload.get("media_urls") or []),
            "media_items": media_items,
            "metadata": metadata,
        },
    }


def _normalize_publication_platform_options(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw_options = value if isinstance(value, dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_platform, raw_value in raw_options.items():
        platform = normalize_publication_platform(raw_platform)
        if not platform or not isinstance(raw_value, dict):
            continue
        option: dict[str, Any] = {}
        scheduled_publish_at = _normalize_scheduled_publish_at(raw_value.get("scheduled_publish_at"))
        if scheduled_publish_at:
            option["scheduled_publish_at"] = scheduled_publish_at
        collection = _normalize_collection_option(raw_value)
        if collection:
            option["collection"] = collection
        category = str(raw_value.get("category") or "").strip()
        if category:
            option["category"] = category[:120]
        visibility_or_publish_mode = str(raw_value.get("visibility_or_publish_mode") or "").strip()
        if visibility_or_publish_mode:
            option["visibility_or_publish_mode"] = visibility_or_publish_mode[:80]
        platform_specific_overrides = raw_value.get("platform_specific_overrides")
        if isinstance(platform_specific_overrides, dict):
            option["platform_specific_overrides"] = platform_specific_overrides
        normalized[platform] = option
    return normalized


def _normalize_scheduled_publish_at(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", text):
        return text
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.isoformat()
    return text[:64]


def _normalize_collection_option(value: dict[str, Any]) -> dict[str, str] | None:
    raw_collection = value.get("collection")
    if isinstance(raw_collection, dict):
        collection_id = str(raw_collection.get("id") or raw_collection.get("collection_id") or "").strip()
        collection_name = str(raw_collection.get("name") or raw_collection.get("title") or raw_collection.get("label") or "").strip()
    else:
        collection_id = str(value.get("collection_id") or "").strip()
        collection_name = str(value.get("collection_name") or raw_collection or "").strip()
    if not collection_id and not collection_name:
        return None
    collection: dict[str, str] = {}
    if collection_id:
        collection["id"] = collection_id[:160]
    if collection_name:
        collection["name"] = collection_name[:160]
    return collection


def map_browser_agent_publication_status(raw_status: Any) -> str:
    status = str(raw_status or "").strip().lower().replace("-", "_")
    if status in {"published", "draft_created", "scheduled_pending"}:
        return status
    if status in {"queued", "submitted", "created", "pending"}:
        return "submitted"
    if status in {"running", "processing", "uploading", "publishing", "reconciling"}:
        return "processing"
    if status in BROWSER_AGENT_HUMAN_STATUSES:
        return "needs_human"
    if status in BROWSER_AGENT_RETRYABLE_STATUSES or status in BROWSER_AGENT_FAILED_STATUSES:
        return "failed"
    return "failed" if status else "processing"


def _apply_browser_agent_task_state(
    attempt: PublicationAttempt,
    run: PublicationAttemptRun | None,
    task: dict[str, Any],
    *,
    response_payload: dict[str, Any],
) -> None:
    now = _utc_now()
    raw_status = str(task.get("status") or task.get("state") or "").strip()
    mapped_status = map_browser_agent_publication_status(raw_status)
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    error = task.get("error") if isinstance(task.get("error"), dict) else {}

    attempt.provider_status = raw_status or attempt.provider_status
    attempt.provider_task_id = str(task.get("task_id") or task.get("id") or attempt.provider_task_id or "").strip() or None
    attempt.provider_execution_id = str(task.get("execution_id") or task.get("run_id") or attempt.provider_execution_id or "").strip() or None
    attempt.response_payload = response_payload
    attempt.status = mapped_status
    attempt.run_status = mapped_status
    if mapped_status == "published":
        attempt.published_at = _parse_datetime(task.get("published_at") or result.get("published_at")) or now
    if mapped_status == "scheduled_pending":
        attempt.scheduled_at = _parse_datetime(task.get("scheduled_publish_at") or result.get("scheduled_publish_at")) or attempt.scheduled_at
    external_post_id = str(result.get("post_id") or task.get("post_id") or "").strip()
    if external_post_id:
        attempt.external_post_id = external_post_id
    external_receipt_id = str(result.get("receipt_id") or task.get("receipt_id") or "").strip()
    if external_receipt_id:
        attempt.external_receipt_id = external_receipt_id
    public_url = _first_public_url(result, task)
    if public_url:
        attempt.external_url = public_url
    error_code = str(error.get("code") or task.get("error_code") or raw_status or "").strip()
    error_message = str(error.get("message") or task.get("error_message") or "").strip()
    if mapped_status in {"failed", "needs_human"}:
        attempt.error_code = error_code or mapped_status
        attempt.error_message = error_message or _publication_status_summary(mapped_status, raw_status)
    elif mapped_status in {"submitted", "processing", "published", "draft_created", "scheduled_pending"}:
        attempt.error_code = None
        attempt.error_message = None
    attempt.operator_summary = _publication_status_summary(mapped_status, raw_status)

    if run is not None:
        run.status = mapped_status
        run.phase = "reconcile" if mapped_status in {"submitted", "processing"} else "completed"
        run.heartbeat_at = now
        run.provider_task_id = attempt.provider_task_id
        run.provider_execution_id = attempt.provider_execution_id
        run.provider_status = attempt.provider_status
        run.result_json = response_payload
        run.error_message = attempt.error_message
        if mapped_status in PUBLICATION_TERMINAL_STATUSES or mapped_status == "scheduled_pending":
            run.completed_at = now


def _mark_publication_attempt_failed(
    attempt: PublicationAttempt,
    run: PublicationAttemptRun | None,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    now = _utc_now()
    can_retry = retryable and int(attempt.retry_count or 0) < int(attempt.max_retries or 0)
    attempt.error_code = code
    attempt.error_message = message
    if can_retry:
        attempt.retry_count = int(attempt.retry_count or 0) + 1
        attempt.status = "queued"
        attempt.run_status = "retry_scheduled"
        attempt.next_retry_at = now + timedelta(seconds=min(900, 30 * (2 ** max(0, attempt.retry_count - 1))))
        attempt.operator_summary = f"browser-agent 暂不可用，已安排第 {attempt.retry_count} 次重试。"
        run_status = "retry_scheduled"
    else:
        attempt.status = "failed"
        attempt.run_status = "failed"
        attempt.operator_summary = f"发布失败：{message}"
        run_status = "failed"
    if run is not None:
        run.status = run_status
        run.phase = "submit"
        run.heartbeat_at = now
        run.completed_at = now
        run.error_message = message


async def _latest_publication_run(session: AsyncSession, attempt_id: str) -> PublicationAttemptRun | None:
    result = await session.execute(
        select(PublicationAttemptRun)
        .where(PublicationAttemptRun.attempt_id == attempt_id)
        .order_by(PublicationAttemptRun.created_at.desc(), PublicationAttemptRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _browser_agent_request_json(
    method: str,
    path: str,
    *,
    base_url: str,
    auth_token: str = "",
    json_payload: dict[str, Any] | None = None,
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    if not normalized_base_url:
        raise RuntimeError("publication_browser_agent_base_url is empty")
    headers: dict[str, str] = {}
    token = str(auth_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{normalized_base_url}{path}"
    if http_client is not None:
        if method.upper() == "POST":
            response = await http_client.post(url, json=json_payload or {}, headers=headers)
        else:
            response = await http_client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"result": payload}
    timeout = httpx.Timeout(float(max(5, request_timeout_sec)), connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method.upper() == "POST":
            response = await client.post(url, json=json_payload or {}, headers=headers)
        else:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"result": payload}


def _extract_browser_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("task", "data", "result"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict) and (value.get("status") or value.get("state") or value.get("task_id") or value.get("id")):
            return value
    return payload if isinstance(payload, dict) else {}


def _first_public_url(*payloads: dict[str, Any]) -> str | None:
    for payload in payloads:
        for key in ("public_url", "post_url", "url", "external_url"):
            value = str(payload.get(key) or "").strip()
            if value and _looks_like_public_publication_url(value):
                return value
    return None


def _looks_like_public_publication_url(value: str) -> bool:
    text = value.strip().lower()
    if not text.startswith(("http://", "https://")):
        return False
    backstage_tokens = ("creator", "studio", "manager", "admin", "dashboard", "publish", "draft")
    return not any(token in text for token in backstage_tokens)


def _publication_status_summary(mapped_status: str, raw_status: str) -> str:
    platform_status = f"（平台状态：{raw_status}）" if raw_status else ""
    if mapped_status == "published":
        return f"已发布并完成公开状态对账{platform_status}。"
    if mapped_status == "scheduled_pending":
        return f"已预约发布，尚未公开{platform_status}。"
    if mapped_status == "draft_created":
        return f"已创建平台草稿，需要人工确认公开{platform_status}。"
    if mapped_status == "needs_human":
        return f"browser-agent 需要人工介入{platform_status}。"
    if mapped_status == "processing":
        return f"browser-agent 正在执行发布{platform_status}。"
    if mapped_status == "submitted":
        return f"已提交 browser-agent，等待执行{platform_status}。"
    return f"发布失败{platform_status}。"


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _build_request_payload(*, plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    tags = [str(item).strip().lstrip("#") for item in (target.get("tags") or []) if str(item).strip()]
    media_path = str(plan.get("media_path") or "").strip()
    collection = target.get("collection") if isinstance(target.get("collection"), dict) else None
    scheduled_publish_at = str(target.get("scheduled_publish_at") or "").strip() or None
    visibility_or_publish_mode = str(target.get("visibility_or_publish_mode") or "").strip() or None
    category = str(target.get("category") or "").strip() or None
    return {
        "title": str(target.get("title") or "").strip(),
        "body": str(target.get("body") or "").strip(),
        "content_kind": "video",
        "hashtags": tags,
        "display_hashtags": [f"#{tag}" for tag in tags],
        "structured_tags": tags,
        "native_topics": [],
        "category": category,
        "collection": collection,
        "visibility_or_publish_mode": visibility_or_publish_mode,
        "scheduled_publish_at": scheduled_publish_at,
        "ui_control_semantics": {
            "schedule_publish": bool(scheduled_publish_at),
            "collection_select": bool(collection),
        },
        "platform_specific_overrides": target.get("platform_specific_overrides") or {},
        "media_items": [
            {
                "kind": "video",
                "local_path": media_path,
                "source_url": None,
                "uploaded_url": None,
                "mime_type": "video/mp4",
            }
        ]
        if media_path
        else [],
        "media_urls": [media_path] if media_path else [],
        "metadata": {
            "adapter": CANONICAL_PUBLICATION_ADAPTER,
            "browser_profile_id": str(
                target.get("browser_profile_id")
                or target.get("credential_ref")
                or target.get("account_label")
                or target.get("platform")
                or ""
            ),
            "credential_id": str(target.get("credential_id") or ""),
            "credential_ref": str(target.get("credential_ref") or ""),
            "account_label": str(target.get("account_label") or ""),
            "creator_profile_id": str(plan.get("creator_profile_id") or ""),
            "creator_profile_name": str(plan.get("creator_profile_name") or ""),
            "publication_guard": plan.get("publication_guard") or {},
        },
        "publication_capability": {
            "adapter": CANONICAL_PUBLICATION_ADAPTER,
            "platform": str(target.get("platform") or ""),
            "requires_local_media": True,
            "supports_scheduled_publish": True,
            "supports_collection_select": True,
        },
        "validation_contract": BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
    }


def _sanitize_profile_id(value: Any, *, fallback: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or fallback or "default").strip()).strip("-")
    return base[:128] or fallback or "default"


def _resolve_render_media_path(render_output: Any | None) -> Path | None:
    if render_output is None:
        return None
    raw = str(getattr(render_output, "output_path", "") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.exists() and path.is_file():
        return path.resolve()
    return None


def _normalize_platform_packages(packaging: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = packaging if isinstance(packaging, dict) else {}
    platform_root = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else raw
    packages: dict[str, dict[str, Any]] = {}
    if not isinstance(platform_root, dict):
        return packages
    for key, value in platform_root.items():
        platform = normalize_publication_platform(key)
        if not platform or not isinstance(value, dict):
            continue
        packages[platform] = dict(value)
    return packages


def _package_has_publish_copy(package: dict[str, Any]) -> bool:
    return bool(_package_primary_title(package) or str(package.get("description") or package.get("body") or "").strip())


def _package_primary_title(package: dict[str, Any]) -> str:
    titles = package.get("titles")
    if isinstance(titles, list):
        for title in titles:
            text = str(title or "").strip()
            if text:
                return text
    return str(package.get("primary_title") or package.get("title") or "").strip()


def _semantic_fingerprint(*, job_id: str, platform: str, title: str, body: str, media_path: str) -> str:
    blob = json.dumps(
        {
            "job_id": job_id,
            "platform": platform,
            "title": re.sub(r"\s+", " ", title).strip(),
            "body": re.sub(r"\s+", " ", body).strip(),
            "media_path": media_path,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _platform_sort_key(platform: str) -> int:
    keys = list(SUPPORTED_PUBLICATION_PLATFORMS)
    try:
        return keys.index(platform)
    except ValueError:
        return len(keys)
