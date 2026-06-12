from __future__ import annotations

from typing import Any


def classify_avatar_runtime_reason_category(reason: str) -> str | None:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return None
    if "slot_timeout" in normalized:
        return "slot_timeout"
    if "call_timeout" in normalized:
        return "call_timeout"
    if "busy_exhausted" in normalized:
        return "busy_exhausted"
    if "provider_response_error" in normalized or normalized.endswith("provider_error") or "provider_error" in normalized:
        return "provider_error"
    return None


def classify_render_or_avatar_reason_category(reason: str) -> str | None:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return None
    avatar_category = classify_avatar_runtime_reason_category(normalized)
    if avatar_category:
        return avatar_category
    if "render_timeout_process" in normalized:
        return "render_timeout_process"
    if "render_timeout_thread" in normalized:
        return "render_timeout_thread"
    if "render_timeout" in normalized:
        return "render_timeout"
    return None


def classify_render_failure_reason(
    *,
    error: str,
    detail: str = "",
    sync_runner: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    normalized_error = str(error or "").strip().lower()
    normalized_detail = str(detail or "").strip().lower()
    haystack = f"{normalized_error}\n{normalized_detail}".strip()
    sync_runner_payload = sync_runner if isinstance(sync_runner, dict) else {}
    if not haystack:
        return None, []
    timeout_strategy = str(sync_runner_payload.get("sync_runner_timeout_strategy") or "").strip().lower()
    timeout_seconds = sync_runner_payload.get("sync_runner_timeout_seconds")
    if ("timeouterror" in haystack or "timeout" in haystack) and (
        "执行超过" in haystack
        or "timeout" in haystack
        or timeout_strategy in {"process", "thread"}
        or timeout_seconds not in (None, "", 0)
    ):
        if timeout_strategy == "process":
            return "render_timeout_process", ["render_timeout"]
        if timeout_strategy == "thread":
            return "render_timeout_thread", ["render_timeout"]
        return "render_timeout", ["render_timeout"]
    if "render_variant_sync_blocked" in haystack:
        return "render_variant_sync_blocked", ["subtitle_sync_issue"]
    if "ffmpeg render failed" in haystack:
        return "ffmpeg_render_failed", ["ffmpeg_render_failed"]
    if "ffmpeg timed overlay render failed" in haystack:
        return "ffmpeg_timed_overlay_render_failed", ["ffmpeg_render_failed"]
    if "ffmpeg insert packaging failed" in haystack:
        return "ffmpeg_insert_packaging_failed", ["ffmpeg_packaging_failed"]
    if "ffmpeg intro/outro packaging failed" in haystack:
        return "ffmpeg_intro_outro_packaging_failed", ["ffmpeg_packaging_failed"]
    if "ffmpeg music/watermark packaging failed" in haystack:
        return "ffmpeg_music_watermark_packaging_failed", ["ffmpeg_packaging_failed"]
    if "ffmpeg multi-track music loop failed" in haystack:
        return "ffmpeg_multi_track_music_loop_failed", ["ffmpeg_packaging_failed"]
    if "ffmpeg packaging clip prepare failed" in haystack:
        return "ffmpeg_packaging_clip_prepare_failed", ["ffmpeg_packaging_failed"]
    if "ffprobe failed" in haystack:
        return "render_ffprobe_failed", ["media_probe_failed"]
    if "cover export failed" in haystack:
        return "cover_export_failed", ["cover_export_failed"]
    return "render_failed", ["render_failed"]


def normalize_render_step_summary_for_reporting(
    render_step: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(render_step or {}) if isinstance(render_step, dict) else {}
    if not payload:
        return {}
    status = str(payload.get("status") or "").strip().lower()
    sync_runner = dict(payload.get("sync_runner") or {}) if isinstance(payload.get("sync_runner"), dict) else {}
    if status != "failed":
        payload.pop("reason", None)
        payload.pop("issue_codes", None)
        return payload

    reason = str(payload.get("reason") or "").strip()
    issue_codes = list(payload.get("issue_codes") or [])
    if not reason or reason == "render_failed":
        inferred_reason, inferred_issue_codes = classify_render_failure_reason(
            error=str(payload.get("error") or "").strip(),
            detail=str(payload.get("detail") or "").strip(),
            sync_runner=sync_runner,
        )
        if inferred_reason:
            payload["reason"] = inferred_reason
        if inferred_issue_codes:
            payload["issue_codes"] = inferred_issue_codes
    elif not issue_codes:
        _, inferred_issue_codes = classify_render_failure_reason(
            error=str(payload.get("error") or "").strip(),
            detail=str(payload.get("detail") or "").strip(),
            sync_runner=sync_runner,
        )
        if inferred_issue_codes:
            payload["issue_codes"] = inferred_issue_codes
    return payload
