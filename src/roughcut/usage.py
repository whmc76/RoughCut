from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any


_STEP_USAGE_SCOPE: ContextVar["_StepUsageScope | None"] = ContextVar("roughcut_step_usage_scope", default=None)
_USAGE_OPERATION: ContextVar[str] = ContextVar("roughcut_usage_operation", default="")

_RECENT_CALL_LIMIT = 24


@dataclass(frozen=True)
class _StepUsageScope:
    job_id: str
    step_id: str
    step_name: str


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_usage_payload(usage: dict[str, Any] | None) -> dict[str, int]:
    payload = usage or {}
    prompt_tokens = _safe_int(payload.get("prompt_tokens"))
    completion_tokens = _safe_int(payload.get("completion_tokens"))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


@contextmanager
def track_step_usage(*, job_id: str | uuid.UUID, step_id: str | uuid.UUID | None, step_name: str):
    if step_id in (None, ""):
        yield
        return

    token = _STEP_USAGE_SCOPE.set(
        _StepUsageScope(
            job_id=str(job_id),
            step_id=str(step_id),
            step_name=str(step_name or "").strip(),
        )
    )
    try:
        yield
    finally:
        _STEP_USAGE_SCOPE.reset(token)


@contextmanager
def track_usage_operation(operation: str):
    label = str(operation or "").strip()
    if not label:
        yield
        return

    token = _USAGE_OPERATION.set(label)
    try:
        yield
    finally:
        _USAGE_OPERATION.reset(token)


async def record_usage_event(
    *,
    provider: str,
    model: str,
    usage: dict[str, Any] | None,
    kind: str = "reasoning",
) -> None:
    scope = _STEP_USAGE_SCOPE.get()
    if scope is None:
        return

    normalized = _normalize_usage_payload(usage)
    operation = _USAGE_OPERATION.get().strip() or "unspecified"
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": str(provider or "").strip(),
        "model": str(model or "").strip(),
        "kind": str(kind or "reasoning").strip() or "reasoning",
        "operation": operation,
        **normalized,
    }

    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        step = await session.get(JobStep, uuid.UUID(scope.step_id))
        if step is None:
            return
        metadata = dict(step.metadata_ or {})
        metadata["llm_usage"] = merge_step_usage_summary(metadata.get("llm_usage"), event)
        step.metadata_ = metadata
        await session.commit()


def merge_step_usage_summary(existing: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    summary = dict(existing or {})
    recent_calls = list(summary.get("recent_calls") or [])
    recent_calls.append(event)
    if len(recent_calls) > _RECENT_CALL_LIMIT:
        recent_calls = recent_calls[-_RECENT_CALL_LIMIT:]

    summary["calls"] = _safe_int(summary.get("calls")) + 1
    summary["prompt_tokens"] = _safe_int(summary.get("prompt_tokens")) + _safe_int(event.get("prompt_tokens"))
    summary["completion_tokens"] = _safe_int(summary.get("completion_tokens")) + _safe_int(event.get("completion_tokens"))
    summary["total_tokens"] = summary["prompt_tokens"] + summary["completion_tokens"]

    by_operation = dict(summary.get("by_operation") or {})
    operation = str(event.get("operation") or "unspecified").strip() or "unspecified"
    op_summary = dict(by_operation.get(operation) or {})
    op_summary["calls"] = _safe_int(op_summary.get("calls")) + 1
    op_summary["prompt_tokens"] = _safe_int(op_summary.get("prompt_tokens")) + _safe_int(event.get("prompt_tokens"))
    op_summary["completion_tokens"] = _safe_int(op_summary.get("completion_tokens")) + _safe_int(event.get("completion_tokens"))
    op_summary["total_tokens"] = op_summary["prompt_tokens"] + op_summary["completion_tokens"]
    by_operation[operation] = op_summary

    by_model = dict(summary.get("by_model") or {})
    model_key = str(event.get("model") or "unknown").strip() or "unknown"
    model_summary = dict(by_model.get(model_key) or {})
    model_summary["provider"] = str(event.get("provider") or model_summary.get("provider") or "").strip()
    model_summary["kind"] = str(event.get("kind") or model_summary.get("kind") or "").strip()
    model_summary["calls"] = _safe_int(model_summary.get("calls")) + 1
    model_summary["prompt_tokens"] = _safe_int(model_summary.get("prompt_tokens")) + _safe_int(event.get("prompt_tokens"))
    model_summary["completion_tokens"] = _safe_int(model_summary.get("completion_tokens")) + _safe_int(event.get("completion_tokens"))
    model_summary["total_tokens"] = model_summary["prompt_tokens"] + model_summary["completion_tokens"]
    by_model[model_key] = model_summary

    summary["by_operation"] = by_operation
    summary["by_model"] = by_model
    summary["recent_calls"] = recent_calls
    summary["last_updated_at"] = event.get("timestamp")
    return summary


def _extract_step_cache_entries(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    cache_block = dict(metadata.get("cache") or {})
    entries: list[dict[str, Any]] = []
    for cache_name, payload in sorted(cache_block.items(), key=lambda item: item[0]):
        details = dict(payload or {})
        entries.append(
            {
                "name": str(cache_name or "").strip(),
                "namespace": str(details.get("namespace") or "").strip(),
                "key": str(details.get("key") or "").strip(),
                "hit": bool(details.get("hit")),
                "usage_baseline": {
                    "calls": _safe_int((details.get("usage_baseline") or {}).get("calls")),
                    "prompt_tokens": _safe_int((details.get("usage_baseline") or {}).get("prompt_tokens")),
                    "completion_tokens": _safe_int((details.get("usage_baseline") or {}).get("completion_tokens")),
                    "total_tokens": _safe_int((details.get("usage_baseline") or {}).get("total_tokens")),
                }
                if isinstance(details.get("usage_baseline"), dict)
                else None,
            }
        )
    return entries


def _empty_cache_summary() -> dict[str, Any]:
    return {
        "total_entries": 0,
        "hits": 0,
        "misses": 0,
        "hit_rate": 0.0,
        "avoided_calls": 0,
        "steps_with_hits": 0,
        "hits_with_usage_baseline": 0,
        "saved_prompt_tokens": 0,
        "saved_completion_tokens": 0,
        "saved_total_tokens": 0,
    }


def _update_cache_summary(summary: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    hit_in_step = False
    for entry in entries:
        summary["total_entries"] += 1
        if bool(entry.get("hit")):
            summary["hits"] += 1
            summary["avoided_calls"] += 1
            hit_in_step = True
            usage_baseline = dict(entry.get("usage_baseline") or {})
            if _safe_int(usage_baseline.get("calls")) > 0 or _safe_int(usage_baseline.get("total_tokens")) > 0:
                summary["hits_with_usage_baseline"] += 1
                summary["saved_prompt_tokens"] += _safe_int(usage_baseline.get("prompt_tokens"))
                summary["saved_completion_tokens"] += _safe_int(usage_baseline.get("completion_tokens"))
                summary["saved_total_tokens"] += _safe_int(usage_baseline.get("total_tokens"))
        else:
            summary["misses"] += 1
    if hit_in_step:
        summary["steps_with_hits"] += 1


def _finalize_cache_summary(summary: dict[str, Any]) -> dict[str, Any]:
    total_entries = _safe_int(summary.get("total_entries"))
    hits = _safe_int(summary.get("hits"))
    hits_with_usage_baseline = _safe_int(summary.get("hits_with_usage_baseline"))
    return {
        "total_entries": total_entries,
        "hits": hits,
        "misses": _safe_int(summary.get("misses")),
        "hit_rate": round(hits / total_entries, 4) if total_entries else 0.0,
        "avoided_calls": _safe_int(summary.get("avoided_calls")),
        "steps_with_hits": _safe_int(summary.get("steps_with_hits")),
        "hits_with_usage_baseline": hits_with_usage_baseline,
        "saved_prompt_tokens": _safe_int(summary.get("saved_prompt_tokens")),
        "saved_completion_tokens": _safe_int(summary.get("saved_completion_tokens")),
        "saved_total_tokens": _safe_int(summary.get("saved_total_tokens")),
        "saved_tokens_hit_rate": round(hits_with_usage_baseline / hits, 4) if hits else 0.0,
    }


def _empty_usage_rollup() -> dict[str, Any]:
    return {
        "jobs": 0,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _build_provider_rows(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provider_rollup: dict[str, dict[str, Any]] = defaultdict(_empty_usage_rollup)
    for model in models or []:
        provider_name = str(model.get("provider") or "").strip()
        if not provider_name:
            continue
        row = provider_rollup[provider_name]
        row["jobs"] += 1
        row["calls"] += _safe_int(model.get("calls"))
        row["prompt_tokens"] += _safe_int(model.get("prompt_tokens"))
        row["completion_tokens"] += _safe_int(model.get("completion_tokens"))
        row["total_tokens"] += _safe_int(model.get("total_tokens"))
    return [
        {
            "provider": provider_name,
            **payload,
        }
        for provider_name, payload in sorted(
            provider_rollup.items(),
            key=lambda item: (-_safe_int(item[1].get("total_tokens")), item[0]),
        )
    ]


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _pick_top_entry(current: dict[str, Any] | None, candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    if _safe_int(candidate.get("total_tokens")) > _safe_int(current.get("total_tokens")):
        return candidate
    return current


def build_job_token_report(steps: list[Any], *, step_labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = step_labels or {}
    totals = {
        "has_telemetry": False,
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "steps": [],
        "models": [],
        "cache": _empty_cache_summary(),
    }
    model_rollup: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "provider": "",
            "kind": "",
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )

    for step in steps or []:
        metadata = dict(getattr(step, "metadata_", None) or {})
        cache_entries = _extract_step_cache_entries(metadata)
        _update_cache_summary(totals["cache"], cache_entries)
        usage = dict(metadata.get("llm_usage") or {})
        prompt_tokens = _safe_int(usage.get("prompt_tokens"))
        completion_tokens = _safe_int(usage.get("completion_tokens"))
        calls = _safe_int(usage.get("calls"))
        total_tokens = prompt_tokens + completion_tokens
        if calls <= 0 and total_tokens <= 0 and not cache_entries:
            continue

        totals["has_telemetry"] = True
        totals["total_calls"] += calls
        totals["total_prompt_tokens"] += prompt_tokens
        totals["total_completion_tokens"] += completion_tokens
        totals["total_tokens"] += total_tokens

        operations: list[dict[str, Any]] = []
        for name, op_usage in sorted(
            dict(usage.get("by_operation") or {}).items(),
            key=lambda item: (
                -_safe_int((item[1] or {}).get("total_tokens")),
                item[0],
            ),
        ):
            operations.append(
                {
                    "operation": name,
                    "calls": _safe_int((op_usage or {}).get("calls")),
                    "prompt_tokens": _safe_int((op_usage or {}).get("prompt_tokens")),
                    "completion_tokens": _safe_int((op_usage or {}).get("completion_tokens")),
                    "total_tokens": _safe_int((op_usage or {}).get("total_tokens")),
                }
            )

        for model_name, model_usage in dict(usage.get("by_model") or {}).items():
            row = model_rollup[str(model_name or "unknown").strip() or "unknown"]
            row["provider"] = str(model_usage.get("provider") or row["provider"] or "").strip()
            row["kind"] = str(model_usage.get("kind") or row["kind"] or "").strip()
            row["calls"] += _safe_int(model_usage.get("calls"))
            row["prompt_tokens"] += _safe_int(model_usage.get("prompt_tokens"))
            row["completion_tokens"] += _safe_int(model_usage.get("completion_tokens"))
            row["total_tokens"] += _safe_int(model_usage.get("total_tokens"))

        totals["steps"].append(
            {
                "step_name": step.step_name,
                "label": labels.get(step.step_name, step.step_name),
                "calls": calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "last_updated_at": usage.get("last_updated_at"),
                "operations": operations,
                "cache_entries": cache_entries,
            }
        )

    totals["steps"].sort(key=lambda item: (-item["total_tokens"], item["step_name"]))
    totals["models"] = [
        {
            "model": model_name,
            **payload,
        }
        for model_name, payload in sorted(
            model_rollup.items(),
            key=lambda item: (-_safe_int(item[1].get("total_tokens")), item[0]),
        )
    ]
    totals["cache"] = _finalize_cache_summary(totals["cache"])
    return totals


def build_jobs_usage_summary(jobs: list[Any], *, step_labels: dict[str, str] | None = None) -> dict[str, Any]:
    labels = step_labels or {}
    totals = {
        "job_count": 0,
        "jobs_with_telemetry": 0,
        "total_calls": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "cache": _empty_cache_summary(),
        "top_steps": [],
        "top_models": [],
        "top_providers": [],
    }
    step_rollup: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "jobs": 0,
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
    )
    model_rollup: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "provider": "",
            "kind": "",
            **_empty_usage_rollup(),
        }
    )
    provider_rollup: dict[str, dict[str, Any]] = defaultdict(_empty_usage_rollup)

    for job in jobs or []:
        totals["job_count"] += 1
        report = build_job_token_report(getattr(job, "steps", None) or [], step_labels=labels)
        if report.get("has_telemetry"):
            totals["jobs_with_telemetry"] += 1
        totals["total_calls"] += _safe_int(report.get("total_calls"))
        totals["total_prompt_tokens"] += _safe_int(report.get("total_prompt_tokens"))
        totals["total_completion_tokens"] += _safe_int(report.get("total_completion_tokens"))
        totals["total_tokens"] += _safe_int(report.get("total_tokens"))
        cache_summary = dict(report.get("cache") or {})
        totals["cache"]["total_entries"] += _safe_int(cache_summary.get("total_entries"))
        totals["cache"]["hits"] += _safe_int(cache_summary.get("hits"))
        totals["cache"]["misses"] += _safe_int(cache_summary.get("misses"))
        totals["cache"]["avoided_calls"] += _safe_int(cache_summary.get("avoided_calls"))
        totals["cache"]["steps_with_hits"] += _safe_int(cache_summary.get("steps_with_hits"))
        totals["cache"]["hits_with_usage_baseline"] += _safe_int(cache_summary.get("hits_with_usage_baseline"))
        totals["cache"]["saved_prompt_tokens"] += _safe_int(cache_summary.get("saved_prompt_tokens"))
        totals["cache"]["saved_completion_tokens"] += _safe_int(cache_summary.get("saved_completion_tokens"))
        totals["cache"]["saved_total_tokens"] += _safe_int(cache_summary.get("saved_total_tokens"))

        for step in report.get("steps") or []:
            row = step_rollup[str(step.get("step_name") or "").strip()]
            row["label"] = str(step.get("label") or row["label"] or "").strip()
            row["jobs"] += 1
            row["calls"] += _safe_int(step.get("calls"))
            row["prompt_tokens"] += _safe_int(step.get("prompt_tokens"))
            row["completion_tokens"] += _safe_int(step.get("completion_tokens"))
            row["total_tokens"] += _safe_int(step.get("total_tokens"))
            cache_entries = list(step.get("cache_entries") or [])
            row["cache_hits"] += sum(1 for entry in cache_entries if bool(entry.get("hit")))
            row["cache_misses"] += sum(1 for entry in cache_entries if not bool(entry.get("hit")))

        for model in report.get("models") or []:
            model_name = str(model.get("model") or "unknown").strip() or "unknown"
            model_row = model_rollup[model_name]
            model_row["provider"] = str(model.get("provider") or model_row.get("provider") or "").strip()
            model_row["kind"] = str(model.get("kind") or model_row.get("kind") or "").strip()
            model_row["jobs"] += 1
            model_row["calls"] += _safe_int(model.get("calls"))
            model_row["prompt_tokens"] += _safe_int(model.get("prompt_tokens"))
            model_row["completion_tokens"] += _safe_int(model.get("completion_tokens"))
            model_row["total_tokens"] += _safe_int(model.get("total_tokens"))

        for provider in _build_provider_rows(list(report.get("models") or [])):
            provider_name = str(provider.get("provider") or "").strip()
            if not provider_name:
                continue
            provider_row = provider_rollup[provider_name]
            provider_row["jobs"] += 1
            provider_row["calls"] += _safe_int(provider.get("calls"))
            provider_row["prompt_tokens"] += _safe_int(provider.get("prompt_tokens"))
            provider_row["completion_tokens"] += _safe_int(provider.get("completion_tokens"))
            provider_row["total_tokens"] += _safe_int(provider.get("total_tokens"))

    totals["cache"] = _finalize_cache_summary(totals["cache"])
    totals["top_steps"] = [
        {
            "step_name": step_name,
            **payload,
        }
        for step_name, payload in sorted(
            step_rollup.items(),
            key=lambda item: (-_safe_int(item[1].get("total_tokens")), item[0]),
        )[:8]
    ]
    totals["top_models"] = [
        {
            "model": model_name,
            **payload,
        }
        for model_name, payload in sorted(
            model_rollup.items(),
            key=lambda item: (-_safe_int(item[1].get("total_tokens")), item[0]),
        )[:8]
    ]
    totals["top_providers"] = [
        {
            "provider": provider_name,
            **payload,
        }
        for provider_name, payload in sorted(
            provider_rollup.items(),
            key=lambda item: (-_safe_int(item[1].get("total_tokens")), item[0]),
        )[:8]
    ]
    return totals


def build_jobs_usage_trend(
    jobs: list[Any],
    *,
    days: int = 7,
    step_labels: dict[str, str] | None = None,
    focus_type: str | None = None,
    focus_name: str | None = None,
    step_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    labels = step_labels or {}
    normalized_days = max(1, min(int(days or 7), 90))
    normalized_focus_type = str(focus_type or "").strip().lower()
    if normalized_focus_type not in {"", "all", "step", "model", "provider"}:
        normalized_focus_type = ""
    normalized_focus_name = str(focus_name or "").strip()
    requested_step_name = str(step_name or "").strip()
    if not normalized_focus_name and requested_step_name:
        normalized_focus_type = "step"
        normalized_focus_name = requested_step_name
    if normalized_focus_type == "all":
        normalized_focus_type = ""
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start_day = anchor.date() - timedelta(days=normalized_days - 1)
    buckets: dict[str, dict[str, Any]] = {}

    for offset in range(normalized_days):
        day = start_day + timedelta(days=offset)
        day_key = day.isoformat()
        buckets[day_key] = {
            "date": day_key,
            "label": day.strftime("%m-%d"),
            "job_count": 0,
            "jobs_with_telemetry": 0,
            "total_calls": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "cache": _empty_cache_summary(),
            "top_entry": None,
            "top_step": None,
        }

    for job in jobs or []:
        job_dt = _coerce_datetime(getattr(job, "updated_at", None) or getattr(job, "created_at", None))
        if job_dt is None:
            continue
        day_key = job_dt.astimezone(timezone.utc).date().isoformat()
        if day_key not in buckets:
            continue
        report = build_job_token_report(getattr(job, "steps", None) or [], step_labels=labels)
        bucket = buckets[day_key]
        bucket["job_count"] += 1
        report_steps = list(report.get("steps") or [])
        report_models = list(report.get("models") or [])
        report_providers = _build_provider_rows(report_models)
        if normalized_focus_type == "step":
            relevant_steps = report_steps
            if normalized_focus_name:
                relevant_steps = [
                    step for step in report_steps if str(step.get("step_name") or "").strip() == normalized_focus_name
                ]
            if relevant_steps:
                bucket["jobs_with_telemetry"] += 1
            bucket["total_calls"] += sum(_safe_int(step.get("calls")) for step in relevant_steps)
            bucket["total_prompt_tokens"] += sum(_safe_int(step.get("prompt_tokens")) for step in relevant_steps)
            bucket["total_completion_tokens"] += sum(_safe_int(step.get("completion_tokens")) for step in relevant_steps)
            bucket["total_tokens"] += sum(_safe_int(step.get("total_tokens")) for step in relevant_steps)
            if not normalized_focus_name:
                cache_summary = dict(report.get("cache") or {})
                bucket["cache"]["total_entries"] += _safe_int(cache_summary.get("total_entries"))
                bucket["cache"]["hits"] += _safe_int(cache_summary.get("hits"))
                bucket["cache"]["misses"] += _safe_int(cache_summary.get("misses"))
                bucket["cache"]["avoided_calls"] += _safe_int(cache_summary.get("avoided_calls"))
                bucket["cache"]["steps_with_hits"] += _safe_int(cache_summary.get("steps_with_hits"))
                bucket["cache"]["hits_with_usage_baseline"] += _safe_int(cache_summary.get("hits_with_usage_baseline"))
                bucket["cache"]["saved_prompt_tokens"] += _safe_int(cache_summary.get("saved_prompt_tokens"))
                bucket["cache"]["saved_completion_tokens"] += _safe_int(cache_summary.get("saved_completion_tokens"))
                bucket["cache"]["saved_total_tokens"] += _safe_int(cache_summary.get("saved_total_tokens"))
            else:
                for step in relevant_steps:
                    _update_cache_summary(bucket["cache"], list(step.get("cache_entries") or []))
            if relevant_steps:
                top_step = relevant_steps[0]
                top_step_entry = {
                    "step_name": str(top_step.get("step_name") or "").strip(),
                    "label": str(top_step.get("label") or "").strip(),
                    "total_tokens": _safe_int(top_step.get("total_tokens")),
                }
                bucket["top_step"] = _pick_top_entry(bucket.get("top_step"), top_step_entry)
                bucket["top_entry"] = _pick_top_entry(bucket.get("top_entry"), {
                    "dimension": "step",
                    "name": str(top_step.get("step_name") or "").strip(),
                    "label": str(top_step.get("label") or "").strip(),
                    "total_tokens": _safe_int(top_step.get("total_tokens")),
                })
        elif normalized_focus_type == "model":
            relevant_models = report_models
            if normalized_focus_name:
                relevant_models = [
                    model for model in report_models if str(model.get("model") or "").strip() == normalized_focus_name
                ]
            if relevant_models:
                bucket["jobs_with_telemetry"] += 1
            bucket["total_calls"] += sum(_safe_int(model.get("calls")) for model in relevant_models)
            bucket["total_prompt_tokens"] += sum(_safe_int(model.get("prompt_tokens")) for model in relevant_models)
            bucket["total_completion_tokens"] += sum(_safe_int(model.get("completion_tokens")) for model in relevant_models)
            bucket["total_tokens"] += sum(_safe_int(model.get("total_tokens")) for model in relevant_models)
            if relevant_models:
                top_model = relevant_models[0]
                bucket["top_entry"] = _pick_top_entry(bucket.get("top_entry"), {
                    "dimension": "model",
                    "name": str(top_model.get("model") or "").strip(),
                    "label": str(top_model.get("model") or "").strip(),
                    "total_tokens": _safe_int(top_model.get("total_tokens")),
                })
        elif normalized_focus_type == "provider":
            relevant_providers = report_providers
            if normalized_focus_name:
                relevant_providers = [
                    provider
                    for provider in report_providers
                    if str(provider.get("provider") or "").strip() == normalized_focus_name
                ]
            if relevant_providers:
                bucket["jobs_with_telemetry"] += 1
            bucket["total_calls"] += sum(_safe_int(provider.get("calls")) for provider in relevant_providers)
            bucket["total_prompt_tokens"] += sum(_safe_int(provider.get("prompt_tokens")) for provider in relevant_providers)
            bucket["total_completion_tokens"] += sum(
                _safe_int(provider.get("completion_tokens")) for provider in relevant_providers
            )
            bucket["total_tokens"] += sum(_safe_int(provider.get("total_tokens")) for provider in relevant_providers)
            if relevant_providers:
                top_provider = relevant_providers[0]
                bucket["top_entry"] = _pick_top_entry(bucket.get("top_entry"), {
                    "dimension": "provider",
                    "name": str(top_provider.get("provider") or "").strip(),
                    "label": str(top_provider.get("provider") or "").strip(),
                    "total_tokens": _safe_int(top_provider.get("total_tokens")),
                })
        else:
            if report.get("has_telemetry"):
                bucket["jobs_with_telemetry"] += 1
            bucket["total_calls"] += _safe_int(report.get("total_calls"))
            bucket["total_prompt_tokens"] += _safe_int(report.get("total_prompt_tokens"))
            bucket["total_completion_tokens"] += _safe_int(report.get("total_completion_tokens"))
            bucket["total_tokens"] += _safe_int(report.get("total_tokens"))
            cache_summary = dict(report.get("cache") or {})
            bucket["cache"]["total_entries"] += _safe_int(cache_summary.get("total_entries"))
            bucket["cache"]["hits"] += _safe_int(cache_summary.get("hits"))
            bucket["cache"]["misses"] += _safe_int(cache_summary.get("misses"))
            bucket["cache"]["avoided_calls"] += _safe_int(cache_summary.get("avoided_calls"))
            bucket["cache"]["steps_with_hits"] += _safe_int(cache_summary.get("steps_with_hits"))
            bucket["cache"]["hits_with_usage_baseline"] += _safe_int(cache_summary.get("hits_with_usage_baseline"))
            bucket["cache"]["saved_prompt_tokens"] += _safe_int(cache_summary.get("saved_prompt_tokens"))
            bucket["cache"]["saved_completion_tokens"] += _safe_int(cache_summary.get("saved_completion_tokens"))
            bucket["cache"]["saved_total_tokens"] += _safe_int(cache_summary.get("saved_total_tokens"))
            if report_steps:
                step = report_steps[0]
                top_step_entry = {
                    "step_name": str(step.get("step_name") or "").strip(),
                    "label": str(step.get("label") or "").strip(),
                    "total_tokens": _safe_int(step.get("total_tokens")),
                }
                bucket["top_step"] = _pick_top_entry(bucket.get("top_step"), top_step_entry)
                bucket["top_entry"] = _pick_top_entry(bucket.get("top_entry"), {
                    "dimension": "step",
                    "name": str(step.get("step_name") or "").strip(),
                    "label": str(step.get("label") or "").strip(),
                    "total_tokens": _safe_int(step.get("total_tokens")),
                })

    points = []
    for day_key in sorted(buckets):
        bucket = buckets[day_key]
        bucket["cache"] = _finalize_cache_summary(bucket["cache"])
        points.append(bucket)

    return {
        "days": normalized_days,
        "focus_type": normalized_focus_type or None,
        "focus_name": normalized_focus_name or None,
        "points": points,
    }
