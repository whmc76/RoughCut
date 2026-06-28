from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Sequence

from sqlalchemy import select

from roughcut.db.models import PublicationAttempt
from roughcut.db.session import get_session_factory
from roughcut.publication import (
    PUBLICATION_ACTIVE_STATUSES,
    PUBLICATION_SUCCESS_STATUSES,
    _extract_publication_dedupe_signature,
    _extract_publication_logical_signature,
    _build_publication_logical_signature_payload,
    _normalize_publication_dedupe_media_path,
)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text_set(values: Sequence[str] | None) -> set[str]:
    return {_normalize_text(item) for item in (values or []) if _normalize_text(item)}


def _normalized_platform_list_from_material_payload(material_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(material_payload, dict):
        return []
    scope_candidates: list[dict[str, Any]] = []
    platform_scope = material_payload.get("platform_scope") if isinstance(material_payload.get("platform_scope"), dict) else {}
    if platform_scope:
        scope_candidates.append(platform_scope)
    material_contract = material_payload.get("material_contract") if isinstance(material_payload.get("material_contract"), dict) else {}
    contract_platform_scope = (
        material_contract.get("platform_scope")
        if isinstance(material_contract.get("platform_scope"), dict)
        else {}
    )
    if contract_platform_scope:
        scope_candidates.append(contract_platform_scope)
    for platform_scope in scope_candidates:
        for key in ("requested_platforms", "covered_platforms"):
            values = [
                _normalize_text(item).lower().replace("_", "-")
                for item in (platform_scope.get(key) or [])
                if _normalize_text(item)
            ]
            if values:
                return list(dict.fromkeys(values))
    candidate = material_payload.get("platforms") if isinstance(material_payload.get("platforms"), (dict, list)) else material_payload
    values: list[str] = []
    if isinstance(candidate, dict):
        values = [
            _normalize_text(item).lower().replace("_", "-")
            for item in candidate.keys()
            if _normalize_text(item)
        ]
    elif isinstance(candidate, list):
        values = [
            _normalize_text(item.get("key") or item.get("platform") or item.get("label") or item.get("name")).lower().replace("_", "-")
            for item in candidate
            if isinstance(item, dict) and _normalize_text(item.get("key") or item.get("platform") or item.get("label") or item.get("name"))
        ]
    return list(dict.fromkeys([item for item in values if item]))


def _normalized_creator_profile_ids_from_material_payload(material_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(material_payload, dict):
        return []
    publication_context = (
        material_payload.get("publication_context")
        if isinstance(material_payload.get("publication_context"), dict)
        else {}
    )
    values = [
        _normalize_text(item)
        for item in (
            material_payload.get("creator_profile_id"),
            publication_context.get("creator_profile_id"),
        )
        if _normalize_text(item)
    ]
    return list(dict.fromkeys(values))


def _iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "astimezone"):
        try:
            return value.astimezone(timezone.utc).isoformat()
        except Exception:
            return str(value)
    return str(value)


def _group_identity(group: dict[str, Any]) -> str:
    if not isinstance(group, dict):
        return ""
    return (
        _normalize_text(group.get("group_signature"))
        or _normalize_text(group.get("logical_signature"))
        or _normalize_text(group.get("dedupe_signature"))
    )


def build_logical_content_signature(
    *,
    platform: str,
    creator_profile_id: str | None,
    browser_profile_id: str | None,
    media_path: str | None = None,
    title: str | None,
    body: str | None,
    tags: Sequence[str] | None,
) -> str:
    payload = _build_publication_logical_signature_payload(
        platform=_normalize_text(platform).lower(),
        content_kind="video",
        media_path=_normalize_text(media_path),
        title=" ".join(_normalize_text(title).split()),
        body=" ".join(_normalize_text(body).split()),
        tags=[
            str(item).strip().lstrip("#")
            for item in (tags or [])
            if str(item).strip()
        ],
    )
    fields = payload.get("fields") if isinstance(payload, dict) else {}
    if not isinstance(fields, dict) or not _normalize_text(fields.get("platform")):
        return ""
    return _normalize_text(payload.get("value"))


def extract_current_content_signatures(
    *,
    material_payload: dict[str, Any] | None,
    media_path: str | None = None,
    target_platforms: Sequence[str] | None,
    target_profile_ids: Sequence[str] | None,
) -> list[str]:
    if not isinstance(material_payload, dict):
        return []
    normalized_platforms = [
        _normalize_text(item).lower().replace("_", "-")
        for item in (target_platforms or [])
        if _normalize_text(item)
    ]
    if not normalized_platforms:
        normalized_platforms = _normalized_platform_list_from_material_payload(material_payload)
    candidate = material_payload.get("platforms") if isinstance(material_payload.get("platforms"), (dict, list)) else material_payload
    platform_payloads: dict[str, dict[str, Any]] = {}
    if isinstance(candidate, dict):
        for key, value in candidate.items():
            normalized_key = _normalize_text(key).lower().replace("_", "-")
            if normalized_key and isinstance(value, dict):
                platform_payloads[normalized_key] = value
    elif isinstance(candidate, list):
        for item in candidate:
            if not isinstance(item, dict):
                continue
            normalized_key = _normalize_text(item.get("key") or item.get("platform") or item.get("label") or item.get("name")).lower().replace("_", "-")
            if normalized_key:
                platform_payloads[normalized_key] = item

    content_signatures: list[str] = []
    browser_profile_id = _normalize_text(next(iter(target_profile_ids or []), ""))
    for platform in normalized_platforms:
        payload = platform_payloads.get(platform) if isinstance(platform_payloads.get(platform), dict) else {}
        if not payload:
            continue
        title = _normalize_text(payload.get("primary_title") or payload.get("title"))
        if not title:
            titles = payload.get("titles") if isinstance(payload.get("titles"), list) else []
            for item in titles:
                if isinstance(item, dict):
                    title = _normalize_text(item.get("text"))
                else:
                    title = _normalize_text(item)
                if title:
                    break
        body = _normalize_text(payload.get("body") or payload.get("description"))
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        signature = build_logical_content_signature(
            platform=platform,
            creator_profile_id="",
            browser_profile_id=browser_profile_id,
            media_path=media_path,
            title=title,
            body=body,
            tags=tags,
        )
        if signature and signature not in content_signatures:
            content_signatures.append(signature)
    return content_signatures


async def build_duplicate_history_gate_report(
    *,
    material_payload: dict[str, Any] | None,
    media_path: str,
    target_platforms: Sequence[str] | None,
    target_profile_ids: Sequence[str] | None,
    allow_republish: bool,
    allow_material_creator_profile_fallback: bool = True,
    limit: int = 20,
    audit_fn: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized_platforms = sorted(
        {
            _normalize_text(item).lower().replace("_", "-")
            for item in (target_platforms or [])
            if _normalize_text(item)
        }
    )
    if not normalized_platforms:
        normalized_platforms = sorted(_normalized_platform_list_from_material_payload(material_payload))
    normalized_profile_ids = sorted({_normalize_text(item) for item in (target_profile_ids or []) if _normalize_text(item)})
    normalized_creator_ids = (
        sorted(_normalized_creator_profile_ids_from_material_payload(material_payload))
        if allow_material_creator_profile_fallback
        else []
    )
    content_signatures = extract_current_content_signatures(
        material_payload=material_payload,
        media_path=media_path,
        target_platforms=normalized_platforms,
        target_profile_ids=normalized_profile_ids,
    )
    resolved_audit_fn = audit_fn or audit_duplicate_publications
    report = await resolved_audit_fn(
        creator_profile_ids=normalized_creator_ids,
        browser_profile_ids=normalized_profile_ids,
        platforms=normalized_platforms,
        media_path=_normalize_text(media_path),
        content_signatures=content_signatures,
        limit=limit,
    )
    if content_signatures:
        fallback_report = await resolved_audit_fn(
            creator_profile_ids=normalized_creator_ids,
            browser_profile_ids=[],
            platforms=normalized_platforms,
            media_path="",
            content_signatures=content_signatures,
            limit=limit,
        )
        primary_groups = [item for item in (report.get("groups") or []) if isinstance(item, dict)]
        fallback_groups = [item for item in (fallback_report.get("groups") or []) if isinstance(item, dict)]
        if fallback_groups:
            merged_groups: dict[str, dict[str, Any]] = {}
            for group in primary_groups:
                group_id = _group_identity(group)
                if group_id:
                    merged_groups[group_id] = dict(group)
            relaxed_used = False
            for group in fallback_groups:
                group_id = _group_identity(group)
                if not group_id:
                    continue
                existing = merged_groups.get(group_id)
                if existing is None:
                    merged_groups[group_id] = dict(group)
                    relaxed_used = True
                    continue
                existing_total = int(existing.get("total_attempts") or 0)
                fallback_total = int(group.get("total_attempts") or 0)
                if fallback_total > existing_total:
                    merged_groups[group_id] = dict(group)
                    relaxed_used = True
            if relaxed_used:
                merged_report = dict(report)
                merged_report["groups"] = list(merged_groups.values())
                merged_report["suspicious_group_count"] = len(merged_report["groups"])
                report = merged_report
                report["profile_filter_relaxed"] = True
            elif not primary_groups:
                report = dict(fallback_report)
                report["profile_filter_relaxed"] = True
        elif not primary_groups:
            report = dict(report)
            report["groups"] = []
            report["suspicious_group_count"] = 0
    groups = [item for item in (report.get("groups") or []) if isinstance(item, dict)]
    failures: list[str] = []
    for group in groups:
        reasons = [str(item).strip() for item in (group.get("reasons") or []) if str(item).strip()]
        title = _normalize_text(group.get("title")) or "(untitled)"
        platform = _normalize_text(group.get("platform")).lower() or "unknown"
        if not reasons:
            reasons = ["duplicate_publication_risk"]
        failures.append(f"{platform}: 命中历史重复发布风险 -> {title} [{', '.join(reasons)}]")
    report["failures"] = failures
    report["status"] = "passed" if not failures or allow_republish else "failed"
    report["allow_republish"] = bool(allow_republish)
    if failures and allow_republish:
        report["status"] = "warn"
        report["warning"] = "检测到历史重复发布风险，但本次显式启用了 --allow-republish。"
    return report


def _extract_attempt_summary(attempt: PublicationAttempt) -> dict[str, Any]:
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    metadata = request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {}
    media_items = [item for item in (request_payload.get("media_items") or []) if isinstance(item, dict)]
    media_path = ""
    for item in media_items:
        media_path = _normalize_text(item.get("local_path"))
        if media_path:
            break
    if not media_path:
        media_urls = [_normalize_text(item) for item in (request_payload.get("media_urls") or []) if _normalize_text(item)]
        media_path = media_urls[0] if media_urls else ""
    dedupe_signature = _extract_publication_dedupe_signature(request_payload)
    logical_signature = _extract_publication_logical_signature(request_payload) or build_logical_content_signature(
        platform=attempt.platform,
        creator_profile_id=attempt.creator_profile_id,
        browser_profile_id=metadata.get("browser_profile_id"),
        media_path=media_path,
        title=request_payload.get("title"),
        body=request_payload.get("body"),
        tags=request_payload.get("tags") if isinstance(request_payload.get("tags"), list) else [],
    )
    return {
        "id": attempt.id,
        "job_id": str(attempt.job_id) if getattr(attempt, "job_id", None) else "",
        "status": _normalize_text(attempt.status).lower(),
        "run_status": _normalize_text(attempt.run_status),
        "provider_status": _normalize_text(attempt.provider_status),
        "provider_task_id": _normalize_text(getattr(attempt, "provider_task_id", "")),
        "platform": _normalize_text(attempt.platform).lower(),
        "creator_profile_id": _normalize_text(attempt.creator_profile_id),
        "account_label": _normalize_text(attempt.account_label),
        "browser_profile_id": _normalize_text(metadata.get("browser_profile_id")),
        "title": _normalize_text(request_payload.get("title")),
        "scheduled_publish_at": _normalize_text(request_payload.get("scheduled_publish_at")),
        "external_url": _normalize_text(attempt.external_url),
        "error_code": _normalize_text(attempt.error_code),
        "updated_at": _iso_or_empty(attempt.updated_at),
        "created_at": _iso_or_empty(attempt.created_at),
        "media_path": media_path,
        "normalized_media_path": _normalize_publication_dedupe_media_path(media_path),
        "body": _normalize_text(request_payload.get("body")),
        "tags": [
            str(item).strip().lstrip("#")
            for item in (request_payload.get("tags") or [])
            if str(item).strip()
        ],
        "dedupe_signature": dedupe_signature,
        "logical_signature": logical_signature,
    }


def _is_safe_retry_queue_duplicate(summary: dict[str, Any]) -> bool:
    return (
        summary.get("status") == "queued"
        and summary.get("run_status") == "retry_scheduled"
        and not summary.get("provider_task_id")
    )


@dataclass
class DuplicateAuditGroup:
    group_signature: str
    logical_signature: str
    dedupe_signature: str
    platform: str
    creator_profile_id: str
    browser_profile_id: str
    media_path: str
    title: str
    total_attempts: int
    success_count: int
    active_count: int
    scheduled_variants: list[str]
    statuses: dict[str, int]
    attempts: list[dict[str, Any]]
    reasons: list[str]


def build_duplicate_groups(
    attempts: Iterable[PublicationAttempt],
    *,
    creator_profile_ids: Sequence[str] | None = None,
    browser_profile_ids: Sequence[str] | None = None,
    platforms: Sequence[str] | None = None,
    media_path: str | None = None,
    content_signatures: Sequence[str] | None = None,
) -> list[DuplicateAuditGroup]:
    normalized_creator_ids = _normalize_text_set(creator_profile_ids)
    normalized_browser_ids = _normalize_text_set(browser_profile_ids)
    normalized_platforms = {_normalize_text(item).lower() for item in (platforms or []) if _normalize_text(item)}
    normalized_media_path = _normalize_publication_dedupe_media_path(media_path)
    normalized_content_signatures = _normalize_text_set(content_signatures)

    grouped: dict[str, list[PublicationAttempt]] = defaultdict(list)
    for attempt in attempts:
        summary = _extract_attempt_summary(attempt)
        if normalized_platforms and summary["platform"] not in normalized_platforms:
            continue
        if normalized_creator_ids and summary["creator_profile_id"] not in normalized_creator_ids:
            continue
        if normalized_browser_ids and summary["browser_profile_id"] not in normalized_browser_ids:
            continue
        if normalized_media_path and summary["normalized_media_path"] != normalized_media_path:
            continue
        if normalized_content_signatures and summary["logical_signature"] not in normalized_content_signatures:
            continue
        group_key = summary["logical_signature"] or summary["dedupe_signature"]
        if not group_key:
            continue
        grouped[group_key].append(attempt)

    suspicious: list[DuplicateAuditGroup] = []
    for group_signature, members in grouped.items():
        ordered = sorted(
            members,
            key=lambda item: item.updated_at or item.created_at or datetime.now(timezone.utc),
            reverse=True,
        )
        summaries = [_extract_attempt_summary(item) for item in ordered]
        success_count = sum(1 for item in summaries if item["status"] in PUBLICATION_SUCCESS_STATUSES)
        active_count = sum(1 for item in summaries if item["status"] in PUBLICATION_ACTIVE_STATUSES)
        active_summaries = [item for item in summaries if item["status"] in PUBLICATION_ACTIVE_STATUSES]
        scheduled_variants = sorted({item["scheduled_publish_at"] for item in summaries if item["scheduled_publish_at"]})
        reasons: list[str] = []
        if success_count > 1:
            reasons.append("multiple_successful_publications")
        safe_retry_queue_duplicates = (
            active_count > 1
            and len(active_summaries) == active_count
            and all(_is_safe_retry_queue_duplicate(item) for item in active_summaries)
            and len({item.get("job_id") for item in active_summaries if item.get("job_id")}) == 1
        )
        if active_count > 1 and not safe_retry_queue_duplicates:
            reasons.append("multiple_active_attempts")
        if len(scheduled_variants) > 1 and len(summaries) > 1:
            reasons.append("multiple_schedule_variants_same_live_content")
        if not reasons:
            continue
        statuses = Counter(item["status"] for item in summaries)
        suspicious.append(
            DuplicateAuditGroup(
                group_signature=group_signature,
                logical_signature=summaries[0]["logical_signature"] if summaries else "",
                dedupe_signature=summaries[0]["dedupe_signature"] if summaries else "",
                platform=summaries[0]["platform"] if summaries else "",
                creator_profile_id=summaries[0]["creator_profile_id"] if summaries else "",
                browser_profile_id=summaries[0]["browser_profile_id"] if summaries else "",
                media_path=summaries[0]["media_path"] if summaries else "",
                title=summaries[0]["title"] if summaries else "",
                total_attempts=len(summaries),
                success_count=success_count,
                active_count=active_count,
                scheduled_variants=scheduled_variants,
                statuses=dict(statuses),
                attempts=summaries,
                reasons=reasons,
            )
        )
    return suspicious


async def audit_duplicate_publications(
    *,
    creator_profile_ids: Sequence[str] | None = None,
    browser_profile_ids: Sequence[str] | None = None,
    platforms: Sequence[str] | None = None,
    media_path: str | None = None,
    content_signatures: Sequence[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(PublicationAttempt).order_by(PublicationAttempt.updated_at.desc(), PublicationAttempt.created_at.desc())
        result = await session.execute(stmt)
        attempts = list(result.scalars().all())

    groups = build_duplicate_groups(
        attempts,
        creator_profile_ids=creator_profile_ids,
        browser_profile_ids=browser_profile_ids,
        platforms=platforms,
        media_path=media_path,
        content_signatures=content_signatures,
    )
    if limit and limit > 0:
        groups = groups[:limit]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "creator_profile_ids": sorted(_normalize_text_set(creator_profile_ids)),
        "browser_profile_ids": sorted(_normalize_text_set(browser_profile_ids)),
        "platforms": sorted({_normalize_text(item).lower() for item in (platforms or []) if _normalize_text(item)}),
        "media_path": _normalize_text(media_path),
        "content_signatures": sorted(_normalize_text_set(content_signatures)),
        "total_attempts_scanned": len(attempts),
        "suspicious_group_count": len(groups),
        "groups": [asdict(group) for group in groups],
    }
