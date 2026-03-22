from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from celery.result import AsyncResult

from roughcut.config import get_settings
from roughcut.pipeline.celery_app import celery_app
from roughcut.telegram.presets import TelegramAgentPreset, get_preset, list_presets
from roughcut.telegram.task_store import TelegramAgentTaskRecord, TelegramAgentTaskStore


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir_path() -> Path:
    settings = get_settings()
    state_dir = Path(str(getattr(settings, "telegram_agent_state_dir", "") or "").strip() or "data/telegram-agent")
    if not state_dir.is_absolute():
        state_dir = _repo_root() / state_dir
    return state_dir


def get_task_store() -> TelegramAgentTaskStore:
    return TelegramAgentTaskStore(_state_dir_path() / "tasks.json")


def create_task_record(
    *,
    chat_id: str,
    provider: str,
    preset: str,
    task_text: str,
    scope_path: str = "",
    job_id: str = "",
    status: str,
    confirmation_required: bool,
) -> TelegramAgentTaskRecord:
    return get_task_store().create_record(
        chat_id=chat_id,
        provider=provider,
        preset=preset,
        task_text=task_text,
        scope_path=scope_path,
        job_id=job_id,
        status=status,
        confirmation_required=confirmation_required,
    )


def submit_agent_task(record: TelegramAgentTaskRecord) -> TelegramAgentTaskRecord:
    preset = get_preset(record.provider, record.preset)
    if preset is None:
        raise ValueError(f"Unknown preset: {record.provider}/{record.preset}")

    celery_app.send_task(
        "roughcut.pipeline.tasks.agent_run_preset",
        kwargs={
            "task_id": record.task_id,
            "chat_id": record.chat_id,
            "provider": record.provider,
            "preset": record.preset,
            "task_text": record.task_text,
            "scope_path": record.scope_path,
            "job_id": record.job_id,
        },
        task_id=record.task_id,
        queue="llm_queue",
    )
    updated = get_task_store().update(record.task_id, status="queued", error_text="", notified=False)
    return updated or record


def confirm_agent_task(task_id: str) -> TelegramAgentTaskRecord | None:
    store = get_task_store()
    record = store.get(task_id)
    if record is None or record.status != "awaiting_confirmation":
        return record
    return submit_agent_task(record)


def cancel_agent_task(task_id: str) -> TelegramAgentTaskRecord | None:
    store = get_task_store()
    record = store.get(task_id)
    if record is None:
        return None
    if record.status in {"success", "failed", "cancelled"}:
        return record
    if record.status != "awaiting_confirmation":
        AsyncResult(task_id, app=celery_app).revoke(terminate=False)
    updated = store.update(
        task_id,
        status="cancelled",
        notified=True,
        error_text="Cancelled by user",
    )
    return updated or record


def get_agent_task_record(task_id: str) -> TelegramAgentTaskRecord | None:
    return get_task_store().get(task_id)


def list_agent_task_records(chat_id: str, *, limit: int = 10) -> list[TelegramAgentTaskRecord]:
    return get_task_store().list_for_chat(chat_id, limit=limit)


def get_agent_task_status(task_id: str) -> dict[str, Any]:
    record = get_agent_task_record(task_id)
    if record is None:
        result = AsyncResult(task_id, app=celery_app)
        return {
            "task_id": task_id,
            "status": _normalize_celery_state(result.state),
            "provider": "",
            "preset": "",
            "result_excerpt": _extract_result_excerpt(result.result),
            "error_text": _extract_error_text(result.result),
        }

    if record.status == "awaiting_confirmation":
        return {
            **asdict(record),
            "status": "awaiting_confirmation",
        }
    if record.status == "cancelled":
        return asdict(record)

    result = AsyncResult(task_id, app=celery_app)
    normalized_state = _normalize_celery_state(result.state)
    result_excerpt = _extract_result_excerpt(result.result)
    error_text = _extract_error_text(result.result)
    result_path = record.result_path
    if normalized_state in {"success", "failed"}:
        result_path = persist_agent_task_result(task_id, result.result)
    updated = get_task_store().update(
        task_id,
        status=normalized_state,
        result_excerpt=result_excerpt or record.result_excerpt,
        error_text=error_text or record.error_text,
        result_path=result_path or record.result_path,
    )
    return asdict(updated or record)


def mark_task_notified(task_id: str) -> TelegramAgentTaskRecord | None:
    return get_task_store().update(task_id, notified=True)


def pending_notification_records() -> list[TelegramAgentTaskRecord]:
    return get_task_store().list_pending_notifications()


def persist_agent_task_result(task_id: str, result: Any) -> str:
    target_dir = _state_dir_path() / "results"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{task_id}.json"
    payload = result if isinstance(result, dict) else {"raw": str(result)}
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target_path)


def load_agent_task_result(task_id: str) -> dict[str, Any] | None:
    record = get_agent_task_record(task_id)
    if record is None or not record.result_path:
        return None
    path = Path(record.result_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else {"raw": payload}


def preset_help_lines() -> list[str]:
    lines = []
    for preset in sorted(list_presets_for_help(), key=lambda item: (item.provider, item.name)):
        guard = "需确认" if preset.requires_confirmation else "直发"
        mode = "可改文件" if preset.allow_edits else "只读"
        lines.append(f"- {preset.provider}/{preset.name}：{preset.description}（{mode}，{guard}）")
    return lines


def list_presets_for_help() -> list[TelegramAgentPreset]:
    return list_presets()


def _normalize_celery_state(state: str) -> str:
    mapping = {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "running",
        "RETRY": "retrying",
        "SUCCESS": "success",
        "FAILURE": "failed",
        "REVOKED": "cancelled",
    }
    return mapping.get(str(state or "").upper(), str(state or "").lower() or "unknown")


def _extract_result_excerpt(result: Any) -> str:
    if isinstance(result, dict):
        text = str(result.get("excerpt") or result.get("stdout") or "").strip()
        if text:
            return text
        return json.dumps(result, ensure_ascii=False)[:1200]
    if result is None:
        return ""
    return str(result).strip()[:1200]


def _extract_error_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("error") or result.get("stderr") or "").strip()[:1200]
    if result is None:
        return ""
    return str(result).strip()[:1200]
