from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from roughcut.config import get_settings, llm_task_route
from roughcut.llm_cache import build_cache_key, digest_payload, load_cached_entry, save_cached_json
from roughcut.prompts.edit_decision import build_multimodal_trim_review_prompt
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.usage import track_usage_operation


ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW = "multimodal_trim_review"
MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION = "multimodal_trim_review.v1"
_DEFAULT_REVIEW_REASONS = {"low_signal_subtitle", "timing_trim", "long_non_dialogue"}
_DEFAULT_FRAME_PADDING_SEC = 0.35
_DEFAULT_FRAME_TIMESTAMPS = (0.15, 0.5, 0.85)

logger = logging.getLogger(__name__)


def _candidate_id(item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "").strip()
    start = round(float(item.get("start", 0.0) or 0.0), 3)
    end = round(float(item.get("end", start) or start), 3)
    source_text = str(item.get("source_text") or "").strip()
    return f"{reason}:{start:.3f}:{end:.3f}:{source_text}"


def multimodal_trim_review_candidates(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [dict(item) for item in candidates if isinstance(item, dict)]


def multimodal_trim_review_candidate_ids(payload: dict[str, Any] | None) -> list[str]:
    return [str(item.get("candidate_id") or "").strip() for item in multimodal_trim_review_candidates(payload) if str(item.get("candidate_id") or "").strip()]


def multimodal_trim_review_matches_cut_analysis(
    payload: dict[str, Any] | None,
    cut_analysis: dict[str, Any] | None,
    *,
    source_name: str = "",
    job_flow_mode: str = "auto",
) -> bool:
    pending = build_multimodal_trim_review_payload(
        cut_analysis,
        source_name=source_name,
        job_flow_mode=job_flow_mode,
    )
    return multimodal_trim_review_candidate_ids(payload) == multimodal_trim_review_candidate_ids(pending)


def build_multimodal_trim_review_payload(
    cut_analysis: dict[str, Any] | None,
    *,
    source_name: str = "",
    job_flow_mode: str = "auto",
) -> dict[str, Any]:
    analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    pending: list[dict[str, Any]] = []
    for item in list(analysis.get("rule_candidates") or []):
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "").strip()
        review_required = bool(item.get("multimodal_review_required"))
        if not review_required and reason not in _DEFAULT_REVIEW_REASONS:
            continue
        pending.append(
            {
                "candidate_id": _candidate_id(item),
                "start": round(float(item.get("start", 0.0) or 0.0), 3),
                "end": round(float(item.get("end", item.get("start", 0.0)) or item.get("start", 0.0) or 0.0), 3),
                "reason": reason,
                "source_text": str(item.get("source_text") or "").strip() or None,
                "score": round(float(item.get("score", 0.0) or 0.0), 3),
                "multimodal_roles": [
                    str(role).strip()
                    for role in list(item.get("multimodal_roles") or [])
                    if str(role).strip()
                ][:4],
                "multimodal_keep_priority": str(item.get("multimodal_keep_priority") or "").strip() or None,
                "multimodal_confidence": round(float(item.get("multimodal_confidence", 0.0) or 0.0), 3),
                "review_trigger": "visual_protection" if review_required else "semantic_uncertainty",
                "review_state": "pending",
            }
        )
    return {
        "schema": MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION,
        "source_name": str(source_name or ""),
        "job_flow_mode": str(job_flow_mode or "auto"),
        "reviewed": False,
        "candidate_count": len(pending),
        "pending_count": len(pending),
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": pending,
        "decisions": [],
    }


def _normalize_multimodal_review_decision(
    payload: dict[str, Any] | None,
    *,
    candidate_id: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"cut", "keep", "unsure"}:
        return None
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    evidence = [str(item).strip() for item in list(payload.get("evidence") or []) if str(item).strip()]
    return {
        "candidate_id": candidate_id,
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "reason": str(payload.get("reason") or "").strip(),
        "evidence": evidence[:4],
        "summary": str(payload.get("summary") or "").strip(),
    }


def _review_source_meta(payload: dict[str, Any], source_meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = dict(source_meta or {})
    source_name = str(payload.get("source_name") or "").strip()
    job_flow_mode = str(payload.get("job_flow_mode") or "").strip()
    if source_name and "source_name" not in meta:
        meta["source_name"] = source_name
    if job_flow_mode and "job_flow_mode" not in meta:
        meta["job_flow_mode"] = job_flow_mode
    return meta


def _review_candidate_priority(item: dict[str, Any]) -> tuple[float, float]:
    return (
        float(item.get("multimodal_confidence", 0.0) or 0.0),
        float(item.get("score", 0.0) or 0.0),
    )


def _resolve_multimodal_trim_review_timeout_seconds(settings: object, *, candidate_count: int) -> float:
    try:
        configured_timeout = float(
            getattr(settings, "multimodal_trim_review_timeout_sec", 20) or 20
        )
    except (TypeError, ValueError):
        configured_timeout = 20.0
    configured_timeout = max(8.0, configured_timeout)
    scaled_timeout = 6.0 + max(1, int(candidate_count)) * 5.0
    return max(configured_timeout, scaled_timeout)


def _extract_candidate_frame_times(start: float, end: float) -> list[float]:
    clamped_start = max(0.0, float(start or 0.0))
    clamped_end = max(clamped_start + 0.05, float(end or clamped_start))
    duration = max(0.05, clamped_end - clamped_start)
    window_start = max(0.0, clamped_start - _DEFAULT_FRAME_PADDING_SEC)
    window_end = max(clamped_end, clamped_end + _DEFAULT_FRAME_PADDING_SEC)
    window_duration = max(duration, window_end - window_start)
    frame_times: list[float] = []
    for ratio in _DEFAULT_FRAME_TIMESTAMPS:
        point = window_start + window_duration * ratio
        frame_times.append(round(min(window_end, max(0.0, point)), 3))
    return sorted(dict.fromkeys(frame_times))


async def _extract_candidate_preview_frames(
    *,
    source_path: Path,
    candidate: dict[str, Any],
    temp_dir: Path,
) -> list[Path]:
    frame_paths: list[Path] = []
    for index, seek_sec in enumerate(
        _extract_candidate_frame_times(
            float(candidate.get("start", 0.0) or 0.0),
            float(candidate.get("end", candidate.get("start", 0.0)) or candidate.get("start", 0.0) or 0.0),
        )
    ):
        output_path = temp_dir / f"candidate_{index + 1}.jpg"
        await _extract_frame(source_path, output_path, seek_sec=seek_sec)
        if output_path.exists():
            frame_paths.append(output_path)
    return frame_paths


async def _extract_frame(video_path: Path, output_path: Path, *, seek_sec: float) -> None:
    settings = get_settings()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(max(0.0, float(seek_sec or 0.0))),
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-update",
                "1",
                "-q:v",
                "2",
                "-vf",
                "scale=1280:-2",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"multimodal trim frame extraction failed: {result.stderr[-500:]}")


async def _review_single_multimodal_candidate(
    *,
    source_path: Path,
    source_meta: dict[str, Any],
    candidate: dict[str, Any],
    timeout_sec: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        return None, None
    cache_namespace = "edit_plan.multimodal_trim_review"
    settings = get_settings()
    fingerprint = {
        "source_path": str(source_path),
        "source_meta": source_meta,
        "candidate": {
            "candidate_id": candidate_id,
            "start": round(float(candidate.get("start", 0.0) or 0.0), 3),
            "end": round(float(candidate.get("end", 0.0) or 0.0), 3),
            "reason": str(candidate.get("reason") or "").strip(),
            "source_text": str(candidate.get("source_text") or "").strip(),
            "review_trigger": str(candidate.get("review_trigger") or "").strip(),
        },
        "provider": str(getattr(settings, "active_reasoning_provider", "") or "").strip(),
        "model": str(getattr(settings, "active_vision_model", "") or "").strip(),
    }
    cache_key = build_cache_key(cache_namespace, fingerprint)
    cached_entry = load_cached_entry(cache_namespace, cache_key)
    if cached_entry is not None:
        cached_result = dict(cached_entry.get("result") or {})
        decision = _normalize_multimodal_review_decision(cached_result, candidate_id=candidate_id)
        if decision is not None:
            decision["cached"] = True
            return decision, cached_result

    with tempfile.TemporaryDirectory(prefix="roughcut-mtrim-") as temp_dir_str:
        frame_paths = await _extract_candidate_preview_frames(
            source_path=source_path,
            candidate=candidate,
            temp_dir=Path(temp_dir_str),
        )
        if not frame_paths:
            raise RuntimeError("multimodal_trim_review_frame_missing")
        prompt = build_multimodal_trim_review_prompt(source_meta=source_meta, candidate=candidate)
        route = llm_task_route("edit_plan", search_enabled=False, settings=settings)
        usage_context = track_usage_operation("edit_plan.multimodal_trim_review")
        with route if route is not None else nullcontext():
            with usage_context:
                content = await asyncio.wait_for(
                    complete_with_images(
                        prompt,
                        frame_paths,
                        max_tokens=500,
                        temperature=0.1,
                        json_mode=True,
                    ),
                    timeout=timeout_sec,
                )
        review_payload = json.loads(extract_json_text(content))
        decision = _normalize_multimodal_review_decision(review_payload, candidate_id=candidate_id)
        if decision is None:
            raise ValueError("multimodal trim review payload was not usable")
        save_cached_json(
            cache_namespace,
            cache_key,
            fingerprint=fingerprint,
            result={
                "verdict": decision["verdict"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "evidence": list(decision["evidence"]),
                "summary": decision["summary"],
            },
        )
        return decision, review_payload


async def review_multimodal_trim_review_payload(
    payload: dict[str, Any] | None,
    *,
    source_path: Path | None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_payload = dict(payload or {}) if isinstance(payload, dict) else {}
    base_payload.setdefault("schema", MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION)
    base_payload.setdefault("candidates", [])
    candidates = multimodal_trim_review_candidates(base_payload)
    base_payload["candidate_count"] = len(candidates)
    settings = get_settings()
    if not bool(getattr(settings, "multimodal_trim_review_enabled", True)):
        base_payload["reviewed"] = False
        base_payload["disabled"] = True
        return base_payload
    if source_path is None or not source_path.exists():
        base_payload["reviewed"] = False
        base_payload["error"] = "multimodal_trim_review_source_missing"
        return base_payload
    if not candidates:
        base_payload["reviewed"] = False
        base_payload["pending_count"] = 0
        base_payload["accepted_count"] = 0
        base_payload["rejected_count"] = 0
        base_payload["decisions"] = []
        return base_payload

    try:
        max_candidates = max(0, int(getattr(settings, "multimodal_trim_review_max_candidates", 4) or 4))
    except (TypeError, ValueError):
        max_candidates = 4
    queued_candidates = sorted(candidates, key=_review_candidate_priority, reverse=True)
    if max_candidates > 0:
        queued_candidates = queued_candidates[:max_candidates]
    review_timeout_sec = _resolve_multimodal_trim_review_timeout_seconds(settings, candidate_count=len(queued_candidates))
    normalized_meta = _review_source_meta(base_payload, source_meta)

    decisions: list[dict[str, Any]] = []
    summaries: list[str] = []
    error_code: str | None = None
    for candidate in queued_candidates:
        try:
            decision, raw_payload = await _review_single_multimodal_candidate(
                source_path=source_path,
                source_meta=normalized_meta,
                candidate=candidate,
                timeout_sec=review_timeout_sec,
            )
            if decision is not None:
                decisions.append(decision)
                summary = str((raw_payload or {}).get("summary") or decision.get("summary") or "").strip()
                if summary:
                    summaries.append(summary)
        except (asyncio.TimeoutError, TimeoutError):
            error_code = "multimodal_trim_review_timeout"
            logger.warning("Multimodal trim review timed out for %s", normalized_meta.get("source_name") or source_path)
        except ValueError as exc:
            error_code = "multimodal_trim_review_failed"
            logger.warning("Multimodal trim review produced an unusable payload for %s: %s", normalized_meta.get("source_name") or source_path, str(exc).strip())
        except Exception:
            error_code = "multimodal_trim_review_failed"
            logger.exception("Multimodal trim review failed for %s", normalized_meta.get("source_name") or source_path)

    min_confidence = float(getattr(settings, "multimodal_trim_review_min_confidence", 0.72) or 0.72)
    decisions_by_id = {str(item.get("candidate_id") or "").strip(): item for item in decisions if str(item.get("candidate_id") or "").strip()}
    reviewed_candidates: list[dict[str, Any]] = []
    accepted_count = 0
    rejected_count = 0
    pending_count = 0
    for candidate in candidates:
        payload_item = dict(candidate)
        candidate_id = str(payload_item.get("candidate_id") or "").strip()
        decision = decisions_by_id.get(candidate_id)
        if decision is None:
            payload_item["review_state"] = "pending"
            pending_count += 1
        else:
            payload_item["review"] = dict(decision)
            verdict = str(decision.get("verdict") or "").strip()
            confidence = float(decision.get("confidence", 0.0) or 0.0)
            if verdict == "cut" and confidence >= min_confidence:
                payload_item["review_state"] = "accepted"
                accepted_count += 1
            elif verdict == "keep" and confidence >= min_confidence:
                payload_item["review_state"] = "rejected"
                rejected_count += 1
            else:
                payload_item["review_state"] = "unsure"
                pending_count += 1
        reviewed_candidates.append(payload_item)

    reviewed_payload = {
        **base_payload,
        "reviewed": bool(decisions),
        "candidates": reviewed_candidates,
        "decisions": decisions,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "pending_count": pending_count,
        "summary": "；".join(dict.fromkeys(summary for summary in summaries if summary))[:500] or None,
    }
    if decisions:
        reviewed_payload["provider"] = str(getattr(settings, "active_reasoning_provider", "") or "").strip() or None
        reviewed_payload["model"] = str(getattr(settings, "active_vision_model", "") or "").strip() or None
    if error_code:
        reviewed_payload["error"] = error_code
    return reviewed_payload
