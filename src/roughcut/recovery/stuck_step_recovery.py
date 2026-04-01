from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from roughcut.db.models import Artifact, Job, JobStep
from roughcut.telegram.acp_bridge import run_bridge

STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE = "stuck_step_diagnostic"
_GPU_SENSITIVE_STEPS = {"transcribe", "avatar_commentary", "render"}


def build_stuck_step_diagnostic(
    *,
    job: Job | Any,
    step: JobStep | Any,
    stale_after_sec: int | None = None,
    applied_action: str = "reset_to_pending",
    now: datetime | None = None,
    repo_root: str | Path | None = None,
    allow_acp: bool = True,
) -> dict[str, Any]:
    current = _coerce_utc(now or datetime.now(timezone.utc))
    local_diagnostic = _build_local_diagnostic(
        job=job,
        step=step,
        stale_after_sec=stale_after_sec,
        applied_action=applied_action,
        now=current,
    )
    if not allow_acp:
        return local_diagnostic

    bridge_payload = {
        "repo_root": str(Path(repo_root).resolve()) if repo_root is not None else _default_repo_root(),
        "prompt": _build_acp_prompt(
            job=job,
            step=step,
            stale_after_sec=stale_after_sec,
            applied_action=applied_action,
            now=current,
        ),
    }
    try:
        result = run_bridge(bridge_payload)
        parsed = _parse_acp_diagnostic(result)
        normalized = _normalize_diagnostic_payload(
            parsed,
            job=job,
            step=step,
            stale_after_sec=stale_after_sec,
            applied_action=applied_action,
            now=current,
        )
        normalized["source"] = "acp"
        normalized["bridge"] = {
            "provider": result.get("provider"),
            "backend": result.get("backend"),
            "fallback_from": result.get("fallback_from"),
        }
        return normalized
    except Exception as exc:
        fallback = dict(local_diagnostic)
        fallback["bridge_error"] = str(exc)
        return fallback


async def record_stuck_step_diagnostic(
    session,
    job: Job | Any,
    step: JobStep | Any,
    *,
    stale_after_sec: int | None = None,
    applied_action: str = "reset_to_pending",
    now: datetime | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    diagnosis = build_stuck_step_diagnostic(
        job=job,
        step=step,
        stale_after_sec=stale_after_sec,
        applied_action=applied_action,
        now=now,
        repo_root=repo_root,
    )
    recorded_at = _coerce_utc(now or datetime.now(timezone.utc))
    data_json = {
        **diagnosis,
        "recorded_at": recorded_at.isoformat(),
    }
    step_metadata = dict(getattr(step, "metadata_", None) or {})
    step_metadata.update(
        {
            "recovery_source": diagnosis["source"],
            "recovery_action": diagnosis["recommended_action"]["kind"],
            "recovery_summary": diagnosis["summary"],
            "recovery_root_cause": diagnosis["root_cause"],
            "updated_at": recorded_at.isoformat(),
        }
    )
    if stale_after_sec is not None:
        step_metadata["recovery_stale_after_sec"] = stale_after_sec
    if diagnosis.get("bridge"):
        step_metadata["recovery_bridge_backend"] = diagnosis["bridge"].get("backend")
    step.metadata_ = step_metadata
    session.add(
        Artifact(
            job_id=job.id,
            step_id=getattr(step, "id", None),
            artifact_type=STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE,
            data_json=data_json,
        )
    )
    return diagnosis


def _build_local_diagnostic(
    *,
    job: Job | Any,
    step: JobStep | Any,
    stale_after_sec: int | None,
    applied_action: str,
    now: datetime,
) -> dict[str, Any]:
    elapsed_seconds = _elapsed_seconds(step=step, now=now)
    last_activity_at = _last_activity_at(step)
    step_name = str(getattr(step, "step_name", "") or "").strip() or "unknown"
    step_status = str(getattr(step, "status", "") or "").strip() or "unknown"
    root_cause, confidence = _infer_local_root_cause(
        step_name=step_name,
        step_status=step_status,
        elapsed_seconds=elapsed_seconds,
        stale_after_sec=stale_after_sec,
        error_message=str(getattr(step, "error_message", "") or "").strip() or None,
    )
    recommended_action = {
        "kind": applied_action,
        "reason": _local_action_reason(step_name=step_name, step_status=step_status, stale_after_sec=stale_after_sec),
    }
    summary = (
        f"{step_name} appears stuck in {step_status} state"
        if step_status
        else f"{step_name} appears stuck"
    )
    if elapsed_seconds is not None:
        summary = f"{summary} for about {int(round(elapsed_seconds))}s"
    if stale_after_sec is not None and elapsed_seconds is not None:
        summary = f"{summary} (stale threshold {stale_after_sec}s)"
    return {
        "source": "local",
        "job_id": str(getattr(job, "id", "") or ""),
        "step_id": str(getattr(step, "id", "") or "") or None,
        "step_name": step_name,
        "status": step_status,
        "summary": summary,
        "root_cause": root_cause,
        "confidence": confidence,
        "recommended_action": recommended_action,
        "applied_action": applied_action,
        "evidence": {
            "attempt": int(getattr(step, "attempt", 0) or 0),
            "elapsed_seconds": elapsed_seconds,
            "last_activity_at": last_activity_at.isoformat() if last_activity_at is not None else None,
            "stale_after_sec": stale_after_sec,
            "error_message": getattr(step, "error_message", None),
            "gpu_sensitive": step_name in _GPU_SENSITIVE_STEPS,
            "metadata": dict(getattr(step, "metadata_", None) or {}),
        },
        "diagnosed_at": now.isoformat(),
    }


def _normalize_diagnostic_payload(
    payload: dict[str, Any],
    *,
    job: Job | Any,
    step: JobStep | Any,
    stale_after_sec: int | None,
    applied_action: str,
    now: datetime,
) -> dict[str, Any]:
    local = _build_local_diagnostic(
        job=job,
        step=step,
        stale_after_sec=stale_after_sec,
        applied_action=applied_action,
        now=now,
    )
    normalized = dict(local)
    normalized.update(
        {
            "source": "acp",
            "summary": _coerce_text(payload.get("summary")) or local["summary"],
            "root_cause": _coerce_text(payload.get("root_cause")) or local["root_cause"],
            "confidence": _coerce_confidence(payload.get("confidence"), fallback=0.7),
            "recommended_action": _coerce_recommended_action(
                payload.get("recommended_action"),
                fallback=local["recommended_action"]["kind"],
                fallback_reason=local["recommended_action"]["reason"],
            ),
            "applied_action": applied_action,
            "evidence": {
                **local["evidence"],
                "acp_payload": payload,
            },
        }
    )
    if "diagnosed_at" in payload:
        normalized["diagnosed_at"] = _coerce_text(payload.get("diagnosed_at")) or normalized["diagnosed_at"]
    return normalized


def _parse_acp_diagnostic(result: dict[str, Any]) -> dict[str, Any]:
    text = ""
    for key in ("stdout", "excerpt", "stderr"):
        value = str(result.get(key) or "").strip()
        if value:
            text = value
            break
    if not text:
        raise ValueError("ACP bridge returned no diagnostic text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("ACP diagnostic response was not valid JSON") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("ACP diagnostic response must be a JSON object")
    return parsed


def _build_acp_prompt(
    *,
    job: Job | Any,
    step: JobStep | Any,
    stale_after_sec: int | None,
    applied_action: str,
    now: datetime,
) -> str:
    lines = [
        "You are diagnosing a stuck RoughCut pipeline step.",
        "Return JSON only with keys: summary, root_cause, confidence, recommended_action, evidence.",
        "recommended_action must be an object with keys kind and reason.",
        "Do not change files or execute the step.",
        "",
        f"job_id: {getattr(job, 'id', '')}",
        f"step_id: {getattr(step, 'id', '')}",
        f"step_name: {getattr(step, 'step_name', '')}",
        f"status: {getattr(step, 'status', '')}",
        f"attempt: {getattr(step, 'attempt', 0)}",
        f"started_at: {_format_dt(getattr(step, 'started_at', None))}",
        f"finished_at: {_format_dt(getattr(step, 'finished_at', None))}",
        f"last_activity_at: {_format_dt(_last_activity_at(step))}",
        f"stale_after_sec: {stale_after_sec if stale_after_sec is not None else ''}",
        f"applied_action: {applied_action}",
        f"diagnosed_at: {now.isoformat()}",
        f"error_message: {getattr(step, 'error_message', '') or ''}",
        f"metadata: {json.dumps(dict(getattr(step, 'metadata_', None) or {}), ensure_ascii=False)}",
    ]
    return "\n".join(lines)


def _infer_local_root_cause(
    *,
    step_name: str,
    step_status: str,
    elapsed_seconds: float | None,
    stale_after_sec: int | None,
    error_message: str | None,
) -> tuple[str, float]:
    lower_error = str(error_message or "").lower()
    if step_status == "running":
        if step_name in _GPU_SENSITIVE_STEPS:
            if elapsed_seconds is not None and stale_after_sec is not None and elapsed_seconds >= stale_after_sec:
                return "GPU-sensitive worker step likely stalled or lost its worker heartbeat.", 0.72
            return "GPU-sensitive worker step is still active but has not produced a recent heartbeat.", 0.64
        return "Worker heartbeat stopped updating, so the step likely stalled or the worker exited.", 0.68
    if step_status == "pending":
        return "The step has not started, which usually means a prerequisite or queue slot is blocking it.", 0.58
    if "gpu" in lower_error or "cuda" in lower_error or "memory" in lower_error:
        return "Previous GPU or memory pressure may have interrupted the step.", 0.6
    return "The step is not progressing and needs supervisor intervention.", 0.5


def _local_action_reason(*, step_name: str, step_status: str, stale_after_sec: int | None) -> str:
    if step_status == "running":
        if step_name in _GPU_SENSITIVE_STEPS:
            return "Clear stale task state, verify the GPU worker, then requeue the step."
        return "Clear stale task state and requeue the step."
    if step_status == "pending":
        return "Check prerequisite steps and queue pressure before re-dispatching."
    if stale_after_sec is not None:
        return "Supervisor should decide whether to retry or escalate after reviewing the diagnostic."
    return "Supervisor should review the diagnostic before taking recovery action."


def _coerce_recommended_action(value: Any, *, fallback: str, fallback_reason: str) -> dict[str, Any]:
    if isinstance(value, dict):
        kind = _coerce_text(value.get("kind")) or fallback
        reason = _coerce_text(value.get("reason")) or fallback_reason
        return {"kind": kind, "reason": reason}
    kind = _coerce_text(value) or fallback
    return {"kind": kind, "reason": fallback_reason}


def _coerce_confidence(value: Any, *, fallback: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return fallback
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _elapsed_seconds(*, step: JobStep | Any, now: datetime) -> float | None:
    last_activity = _last_activity_at(step)
    if last_activity is None:
        return None
    return max(0.0, (now - last_activity).total_seconds())


def _last_activity_at(step: JobStep | Any) -> datetime | None:
    metadata = dict(getattr(step, "metadata_", None) or {})
    updated_at = metadata.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        try:
            return _coerce_utc(datetime.fromisoformat(updated_at))
        except ValueError:
            pass
    started_at = getattr(step, "started_at", None)
    if started_at is not None:
        return _coerce_utc(started_at)
    return None


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return _coerce_utc(value).isoformat()


def _default_repo_root() -> str:
    return str(Path(__file__).resolve().parents[3])
