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
from roughcut.edit.cut_analysis import summarize_cut_analysis_candidate_metrics
from roughcut.edit.rule_registry import rule_multimodal_review_trigger
from roughcut.llm_cache import build_cache_key, digest_payload, load_cached_entry, save_cached_json
from roughcut.prompts.edit_decision import build_multimodal_trim_review_batch_prompt
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.storage.s3 import get_storage
from roughcut.usage import track_usage_operation


ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW = "multimodal_trim_review"
MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION = "multimodal_trim_review.v1"
_DEFAULT_FRAME_PADDING_SEC = 0.35
_DEFAULT_FRAME_TIMESTAMPS = (0.15, 0.5, 0.85)
_SEMANTIC_UNCERTAINTY_FRAME_TIMESTAMPS = (0.5,)

logger = logging.getLogger(__name__)


def _resolve_multimodal_review_source_path(source_path: Path | None) -> Path | None:
    if source_path is None:
        return None
    candidate = Path(source_path).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate
    resolve_path = getattr(get_storage(), "resolve_path", None)
    if callable(resolve_path):
        resolved = resolve_path(str(source_path))
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


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


def multimodal_trim_review_decisions(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in decisions:
        decision = _normalize_multimodal_review_decision(item, candidate_id=str((item or {}).get("candidate_id") or "").strip())
        if decision is not None:
            normalized.append(decision)
    return normalized


def multimodal_trim_review_min_confidence(min_confidence: float | None = None) -> float:
    if min_confidence is not None:
        try:
            return float(min_confidence)
        except (TypeError, ValueError):
            pass
    return float(getattr(get_settings(), "multimodal_trim_review_min_confidence", 0.72) or 0.72)


def multimodal_trim_review_auto_cut_candidates(
    cut_analysis: dict[str, Any] | None,
    *,
    min_confidence: float | None = None,
) -> list[dict[str, Any]]:
    analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    threshold = multimodal_trim_review_min_confidence(min_confidence)
    candidates: list[dict[str, Any]] = []
    for raw in list(analysis.get("rule_candidates") or []):
        if not isinstance(raw, dict):
            continue
        decision = raw.get("multimodal_review") if isinstance(raw.get("multimodal_review"), dict) else {}
        verdict = str(decision.get("verdict") or "").strip().lower()
        confidence = float(decision.get("confidence", 0.0) or 0.0)
        if verdict == "cut" and confidence >= threshold:
            candidates.append(dict(raw))
    return candidates


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


def apply_multimodal_trim_review_to_cut_analysis(
    cut_analysis: dict[str, Any] | None,
    review_payload: dict[str, Any] | None,
    *,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    analysis = dict(cut_analysis or {}) if isinstance(cut_analysis, dict) else {}
    review = review_payload if isinstance(review_payload, dict) else {}
    decisions_by_id = {
        str(item.get("candidate_id") or "").strip(): item
        for item in multimodal_trim_review_decisions(review_payload)
        if str(item.get("candidate_id") or "").strip()
    }
    threshold = multimodal_trim_review_min_confidence(min_confidence)
    reviewed_candidates: list[dict[str, Any]] = []
    vetoed_candidate_count = 0
    for raw in list(analysis.get("rule_candidates") or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        decision = decisions_by_id.get(_candidate_id(item))
        if decision is not None:
            item["multimodal_review"] = dict(decision)
            verdict = str(decision.get("verdict") or "").strip().lower()
            confidence = float(decision.get("confidence", 0.0) or 0.0)
            if verdict == "keep" and confidence >= threshold:
                vetoed_candidate_count += 1
                continue
        reviewed_candidates.append(item)
    analysis["rule_candidates"] = reviewed_candidates
    analysis.update(
        summarize_cut_analysis_candidate_metrics(
            analysis.get("accepted_cuts"),
            reviewed_candidates,
        )
    )
    analysis["multimodal_trim_review_summary"] = {
        "reviewed": bool(review.get("reviewed")),
        "candidate_count": int(review.get("candidate_count") or len(list(review.get("candidates") or [])) or 0),
        "decision_count": len(decisions_by_id),
        "accepted_count": int(review.get("accepted_count") or 0),
        "rejected_count": int(review.get("rejected_count") or 0),
        "pending_count": int(review.get("pending_count") or 0),
        "unsure_count": int(review.get("unsure_count") or 0),
        "vetoed_candidate_count": vetoed_candidate_count,
        "provider": str(review.get("provider") or "").strip() or None,
        "model": str(review.get("model") or "").strip() or None,
        "error": str(review.get("error") or "").strip() or None,
        "summary": str(review.get("summary") or "").strip() or None,
    }
    return analysis


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
        review_trigger = rule_multimodal_review_trigger(
            reason,
            explicit_review_required=bool(item.get("multimodal_review_required")),
        )
        if review_trigger is None:
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
                "review_trigger": review_trigger,
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
        "unsure_count": 0,
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
    decision = {
        "candidate_id": candidate_id,
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "reason": str(payload.get("reason") or "").strip(),
        "evidence": evidence[:4],
        "summary": str(payload.get("summary") or "").strip(),
    }
    source = str(payload.get("source") or "").strip()
    if source:
        decision["source"] = source
    return decision


def _deterministic_boundary_trim_decision(candidate: dict[str, Any]) -> dict[str, Any] | None:
    reason = str(candidate.get("reason") or "").strip()
    source_text = str(candidate.get("source_text") or "").strip()
    if reason != "timing_trim" or source_text:
        return None
    try:
        start = max(0.0, float(candidate.get("start", 0.0) or 0.0))
        end = max(start, float(candidate.get("end", start) or start))
    except (TypeError, ValueError):
        return None
    duration = max(0.0, end - start)
    if duration > 1.5:
        return None
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        return None
    return {
        "candidate_id": candidate_id,
        "verdict": "cut",
        "confidence": 0.86,
        "reason": "无口播文本的短边界微修剪，按确定性边界规则收口。",
        "evidence": [f"duration={duration:.3f}s", "source_text_empty", "reason=timing_trim"],
        "summary": "短边界无口播候选已按规则收口，无需视觉复核。",
        "source": "deterministic_boundary_trim",
    }


def _deterministic_failed_attempt_decision(candidate: dict[str, Any]) -> dict[str, Any] | None:
    reason = str(candidate.get("reason") or "").strip()
    if reason != "failed_attempt":
        return None
    source_text = str(candidate.get("source_text") or "").strip()
    if not source_text:
        return None
    try:
        start = max(0.0, float(candidate.get("start", 0.0) or 0.0))
        end = max(start, float(candidate.get("end", start) or start))
    except (TypeError, ValueError):
        return None
    duration = max(0.0, end - start)
    if duration > 20.0:
        return None
    failed_markers = ("失败", "错误", "无效", "没成功", "没打开", "没甩开", "等会儿再来")
    replacement_markers = ("随后", "后面", "之后", "随即", "重新", "正确", "完整展示", "成功")
    if not any(marker in source_text for marker in failed_markers):
        return None
    if not any(marker in source_text for marker in replacement_markers):
        return None
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        return None
    return {
        "candidate_id": candidate_id,
        "verdict": "cut",
        "confidence": 0.88,
        "reason": "文本语义已确认失败尝试且随后有正确/完整展示，按废片发现结果收口。",
        "evidence": [f"duration={duration:.3f}s", "reason=failed_attempt", "replacement_success_mentioned"],
        "summary": "失败尝试候选已按语义证据收口，无需等待视觉复核。",
        "source": "deterministic_failed_attempt",
    }


def _deterministic_multimodal_review_decision(candidate: dict[str, Any]) -> dict[str, Any] | None:
    return _deterministic_boundary_trim_decision(candidate) or _deterministic_failed_attempt_decision(candidate)


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


def _resolve_multimodal_trim_review_timeout_seconds(
    settings: object,
    *,
    candidate_count: int,
    image_count: int,
) -> float:
    try:
        configured_timeout = float(
            getattr(settings, "multimodal_trim_review_timeout_sec", 20) or 20
        )
    except (TypeError, ValueError):
        configured_timeout = 20.0
    configured_timeout = max(8.0, configured_timeout)
    scaled_timeout = 18.0 + max(1, int(image_count)) * 10.0
    return max(configured_timeout, scaled_timeout)


def _candidate_frame_timestamps(candidate: dict[str, Any] | None) -> tuple[float, ...]:
    if str((candidate or {}).get("review_trigger") or "").strip() == "semantic_uncertainty":
        return _SEMANTIC_UNCERTAINTY_FRAME_TIMESTAMPS
    return _DEFAULT_FRAME_TIMESTAMPS


def _extract_candidate_frame_times(start: float, end: float, *, candidate: dict[str, Any] | None = None) -> list[float]:
    clamped_start = max(0.0, float(start or 0.0))
    clamped_end = max(clamped_start + 0.05, float(end or clamped_start))
    duration = max(0.05, clamped_end - clamped_start)
    window_start = max(0.0, clamped_start - _DEFAULT_FRAME_PADDING_SEC)
    window_end = max(clamped_end, clamped_end + _DEFAULT_FRAME_PADDING_SEC)
    window_duration = max(duration, window_end - window_start)
    frame_times: list[float] = []
    for ratio in _candidate_frame_timestamps(candidate):
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
            candidate=candidate,
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


def _multimodal_trim_review_cache_fingerprint(
    *,
    source_path: Path,
    source_meta: dict[str, Any],
    candidate: dict[str, Any],
    settings: object,
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    return {
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


def _load_cached_multimodal_trim_review_decision(
    *,
    source_path: Path,
    source_meta: dict[str, Any],
    candidate: dict[str, Any],
    settings: object,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    cache_namespace = "edit_plan.multimodal_trim_review"
    fingerprint = _multimodal_trim_review_cache_fingerprint(
        source_path=source_path,
        source_meta=source_meta,
        candidate=candidate,
        settings=settings,
    )
    cache_key = build_cache_key(cache_namespace, fingerprint)
    cached_entry = load_cached_entry(cache_namespace, cache_key)
    if cached_entry is None:
        return None, None, cache_key
    cached_result = dict(cached_entry.get("result") or {})
    decision = _normalize_multimodal_review_decision(
        cached_result,
        candidate_id=str(candidate.get("candidate_id") or "").strip(),
    )
    if decision is not None:
        decision["cached"] = True
    return decision, cached_result, cache_key


def _save_multimodal_trim_review_decision_cache(
    *,
    cache_key: str,
    source_path: Path,
    source_meta: dict[str, Any],
    candidate: dict[str, Any],
    decision: dict[str, Any],
    provider: str,
    model: str,
) -> None:
    cache_namespace = "edit_plan.multimodal_trim_review"
    save_cached_json(
        cache_namespace,
        cache_key,
        fingerprint={
            "source_path": str(source_path),
            "source_meta": source_meta,
            "candidate": {
                "candidate_id": str(candidate.get("candidate_id") or "").strip(),
                "start": round(float(candidate.get("start", 0.0) or 0.0), 3),
                "end": round(float(candidate.get("end", 0.0) or 0.0), 3),
                "reason": str(candidate.get("reason") or "").strip(),
                "source_text": str(candidate.get("source_text") or "").strip(),
                "review_trigger": str(candidate.get("review_trigger") or "").strip(),
            },
            "provider": str(provider or "").strip(),
            "model": str(model or "").strip(),
        },
        result={
            "verdict": decision["verdict"],
            "confidence": decision["confidence"],
            "reason": decision["reason"],
            "evidence": list(decision["evidence"]),
            "summary": decision["summary"],
        },
    )


async def _review_multimodal_candidate_batch(
    *,
    source_path: Path,
    source_meta: dict[str, Any],
    candidates: list[dict[str, Any]],
    timeout_sec: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = get_settings()
    decisions: list[dict[str, Any]] = []
    raw_decisions_by_id: dict[str, dict[str, Any]] = {}
    unresolved: list[tuple[dict[str, Any], str]] = []
    for candidate in candidates:
        decision, raw_payload, cache_key = _load_cached_multimodal_trim_review_decision(
            source_path=source_path,
            source_meta=source_meta,
            candidate=candidate,
            settings=settings,
        )
        if decision is not None:
            decisions.append(decision)
            raw_decisions_by_id[str(candidate.get("candidate_id") or "").strip()] = dict(raw_payload or {})
            continue
        unresolved.append((candidate, cache_key))
    if not unresolved:
        return decisions, {"decisions": list(raw_decisions_by_id.values())}

    with tempfile.TemporaryDirectory(prefix="roughcut-mtrim-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        prompt_candidates: list[dict[str, Any]] = []
        image_paths: list[Path] = []
        skipped_frame_missing: list[dict[str, Any]] = []
        for batch_index, (candidate, _cache_key) in enumerate(unresolved, start=1):
            candidate_dir = temp_dir / f"candidate_{batch_index}"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            frame_paths = await _extract_candidate_preview_frames(
                source_path=source_path,
                candidate=candidate,
                temp_dir=candidate_dir,
            )
            if not frame_paths:
                skipped_frame_missing.append(
                    {
                        "candidate_id": str(candidate.get("candidate_id") or "").strip(),
                        "start": round(float(candidate.get("start", 0.0) or 0.0), 3),
                        "end": round(float(candidate.get("end", 0.0) or 0.0), 3),
                        "reason": "multimodal_trim_review_frame_missing",
                    }
                )
                continue
            first_frame_index = len(image_paths) + 1
            image_paths.extend(frame_paths)
            prompt_candidates.append(
                {
                    "candidate_id": str(candidate.get("candidate_id") or "").strip(),
                    "start": round(float(candidate.get("start", 0.0) or 0.0), 3),
                    "end": round(float(candidate.get("end", 0.0) or 0.0), 3),
                    "reason": str(candidate.get("reason") or "").strip(),
                    "source_text": str(candidate.get("source_text") or "").strip() or None,
                    "review_trigger": str(candidate.get("review_trigger") or "").strip() or None,
                    "frame_count": len(frame_paths),
                    "frame_indices": [first_frame_index, len(image_paths)],
                }
            )
        if not prompt_candidates:
            return decisions, {
                "decisions": list(raw_decisions_by_id.values()),
                "skipped_frame_missing": skipped_frame_missing,
            }
        prompt = build_multimodal_trim_review_batch_prompt(
            source_meta=source_meta,
            candidates=prompt_candidates,
        )
        route = llm_task_route("edit_plan", search_enabled=False, settings=settings)
        usage_context = track_usage_operation("edit_plan.multimodal_trim_review")
        with route if route is not None else nullcontext():
            with usage_context:
                content = await asyncio.wait_for(
                    complete_with_images(
                        prompt,
                        image_paths,
                        max_tokens=700,
                        temperature=0.1,
                        json_mode=True,
                    ),
                    timeout=timeout_sec,
                )
        review_payload = json.loads(extract_json_text(content))
        raw_decisions = list(review_payload.get("decisions") or [])
        if not raw_decisions and len(unresolved) == 1 and isinstance(review_payload, dict):
            only_candidate_id = str(unresolved[0][0].get("candidate_id") or "").strip()
            normalized_single = _normalize_multimodal_review_decision(review_payload, candidate_id=only_candidate_id)
            if normalized_single is not None:
                raw_decisions = [
                    {
                        "candidate_id": only_candidate_id,
                        "verdict": normalized_single["verdict"],
                        "confidence": normalized_single["confidence"],
                        "reason": normalized_single["reason"],
                        "evidence": list(normalized_single["evidence"]),
                        "summary": normalized_single["summary"],
                    }
                ]
        raw_by_id = {
            str(item.get("candidate_id") or "").strip(): dict(item)
            for item in raw_decisions
            if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
        }
        for candidate, cache_key in unresolved:
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            raw_item = raw_by_id.get(candidate_id)
            decision = _normalize_multimodal_review_decision(raw_item, candidate_id=candidate_id) if raw_item else None
            if decision is None:
                continue
            decisions.append(decision)
            raw_decisions_by_id[candidate_id] = raw_item or {}
            _save_multimodal_trim_review_decision_cache(
                cache_key=cache_key,
                source_path=source_path,
                source_meta=source_meta,
                candidate=candidate,
                decision=decision,
                provider=str(getattr(settings, "active_reasoning_provider", "") or "").strip(),
                model=str(getattr(settings, "active_vision_model", "") or "").strip(),
            )
        return decisions, {
            "summary": str(review_payload.get("summary") or "").strip(),
            "decisions": list(raw_decisions_by_id.values()),
            "skipped_frame_missing": skipped_frame_missing,
        }


async def _review_multimodal_candidates_resilient(
    *,
    source_path: Path,
    source_meta: dict[str, Any],
    candidates: list[dict[str, Any]],
    timeout_sec: float,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    try:
        decisions, raw_payload = await _review_multimodal_candidate_batch(
            source_path=source_path,
            source_meta=source_meta,
            candidates=candidates,
            timeout_sec=timeout_sec,
        )
        summaries: list[str] = []
        batch_summary = str((raw_payload or {}).get("summary") or "").strip()
        if batch_summary:
            summaries.append(batch_summary)
        skipped_frame_missing = list((raw_payload or {}).get("skipped_frame_missing") or [])
        if skipped_frame_missing:
            summaries.append(f"多模态候选缺少预览帧 {len(skipped_frame_missing)} 条，已保留为待复核。")
        for decision in decisions:
            summary = str((decision or {}).get("summary") or "").strip()
            if summary:
                summaries.append(summary)
        return decisions, summaries, False
    except Exception:
        if len(candidates) <= 1:
            raise
        midpoint = max(1, len(candidates) // 2)
        left_decisions, left_summaries, left_split = await _review_multimodal_candidates_resilient(
            source_path=source_path,
            source_meta=source_meta,
            candidates=candidates[:midpoint],
            timeout_sec=timeout_sec,
        )
        right_decisions, right_summaries, right_split = await _review_multimodal_candidates_resilient(
            source_path=source_path,
            source_meta=source_meta,
            candidates=candidates[midpoint:],
            timeout_sec=timeout_sec,
        )
        return left_decisions + right_decisions, left_summaries + right_summaries, True


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
    resolved_source_path = _resolve_multimodal_review_source_path(source_path)
    if resolved_source_path is None:
        base_payload["reviewed"] = False
        base_payload["error"] = "multimodal_trim_review_source_missing"
        return base_payload
    if not candidates:
        base_payload["reviewed"] = False
        base_payload["pending_count"] = 0
        base_payload["unsure_count"] = 0
        base_payload["accepted_count"] = 0
        base_payload["rejected_count"] = 0
        base_payload["decisions"] = []
        return base_payload

    try:
        max_candidates = max(0, int(getattr(settings, "multimodal_trim_review_max_candidates", 4) or 4))
    except (TypeError, ValueError):
        max_candidates = 4
    deterministic_decisions: list[dict[str, Any]] = []
    model_review_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        deterministic_decision = _deterministic_multimodal_review_decision(candidate)
        if deterministic_decision is not None:
            deterministic_decisions.append(deterministic_decision)
        else:
            model_review_candidates.append(candidate)

    queued_candidates = sorted(model_review_candidates, key=_review_candidate_priority, reverse=True)
    if max_candidates > 0:
        queued_candidates = queued_candidates[:max_candidates]
    total_frame_count = sum(len(_candidate_frame_timestamps(candidate)) for candidate in queued_candidates)
    review_timeout_sec = _resolve_multimodal_trim_review_timeout_seconds(
        settings,
        candidate_count=len(queued_candidates),
        image_count=total_frame_count,
    )
    normalized_meta = _review_source_meta(base_payload, source_meta)

    decisions: list[dict[str, Any]] = list(deterministic_decisions)
    summaries: list[str] = [
        str(item.get("summary") or "").strip()
        for item in deterministic_decisions
        if str(item.get("summary") or "").strip()
    ]
    error_code: str | None = None
    model_review_decision_count = 0
    if queued_candidates:
        try:
            model_decisions, model_summaries, used_split_fallback = await _review_multimodal_candidates_resilient(
                source_path=resolved_source_path,
                source_meta=normalized_meta,
                candidates=queued_candidates,
                timeout_sec=review_timeout_sec,
            )
            model_review_decision_count = len(model_decisions)
            decisions.extend(model_decisions)
            summaries.extend(model_summaries)
            if used_split_fallback and len(model_decisions) < len(queued_candidates):
                error_code = "multimodal_trim_review_timeout"
        except (asyncio.TimeoutError, TimeoutError):
            error_code = "multimodal_trim_review_timeout"
            logger.warning(
                "Multimodal trim review timed out for %s",
                normalized_meta.get("source_name") or resolved_source_path,
            )
        except ValueError as exc:
            error_code = "multimodal_trim_review_failed"
            logger.warning(
                "Multimodal trim review produced an unusable payload for %s: %s",
                normalized_meta.get("source_name") or resolved_source_path,
                str(exc).strip(),
            )
        except Exception:
            error_code = "multimodal_trim_review_failed"
            logger.exception(
                "Multimodal trim review failed for %s",
                normalized_meta.get("source_name") or resolved_source_path,
            )

    min_confidence = float(getattr(settings, "multimodal_trim_review_min_confidence", 0.72) or 0.72)
    decisions_by_id = {str(item.get("candidate_id") or "").strip(): item for item in decisions if str(item.get("candidate_id") or "").strip()}
    reviewed_candidates: list[dict[str, Any]] = []
    accepted_count = 0
    rejected_count = 0
    pending_count = 0
    unsure_count = 0
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
                unsure_count += 1
        reviewed_candidates.append(payload_item)

    reviewed_payload = {
        **base_payload,
        "reviewed": bool(decisions),
        "candidates": reviewed_candidates,
        "decisions": decisions,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "pending_count": pending_count,
        "unsure_count": unsure_count,
        "summary": "；".join(dict.fromkeys(summary for summary in summaries if summary))[:500] or None,
    }
    if model_review_decision_count > 0:
        reviewed_payload["provider"] = str(getattr(settings, "active_reasoning_provider", "") or "").strip() or None
        reviewed_payload["model"] = str(getattr(settings, "active_vision_model", "") or "").strip() or None
    if error_code:
        reviewed_payload["error"] = error_code
    return reviewed_payload
