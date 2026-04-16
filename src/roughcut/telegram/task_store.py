from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TelegramAgentTaskRecord:
    task_id: str
    chat_id: str
    provider: str
    preset: str
    task_text: str
    scope_path: str
    job_id: str
    status: str
    created_at: str
    updated_at: str
    confirmation_required: bool = False
    notified: bool = False
    result_excerpt: str = ""
    error_text: str = ""
    result_path: str = ""
    execution_cwd: str = ""
    workspace_mode: str = ""
    workspace_root: str = ""


class TelegramAgentTaskStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def list_records(self) -> list[TelegramAgentTaskRecord]:
        data = self._read_all()
        records: list[TelegramAgentTaskRecord] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                records.append(TelegramAgentTaskRecord(**item))
            except TypeError:
                continue
        return records

    def get(self, task_id: str) -> TelegramAgentTaskRecord | None:
        for record in self.list_records():
            if record.task_id == str(task_id).strip():
                return record
        return None

    def upsert(self, record: TelegramAgentTaskRecord) -> TelegramAgentTaskRecord:
        records = self.list_records()
        replaced = False
        for index, item in enumerate(records):
            if item.task_id == record.task_id:
                records[index] = record
                replaced = True
                break
        if not replaced:
            records.insert(0, record)
        self._write_all(records[:200])
        return record

    def update(self, task_id: str, **changes: object) -> TelegramAgentTaskRecord | None:
        record = self.get(task_id)
        if record is None:
            return None
        for key, value in changes.items():
            if hasattr(record, key):
                setattr(record, key, value)  # type: ignore[arg-type]
        record.updated_at = utcnow_iso()
        self.upsert(record)
        return record

    def list_for_chat(self, chat_id: str, *, limit: int = 10) -> list[TelegramAgentTaskRecord]:
        matches = [item for item in self.list_records() if item.chat_id == str(chat_id).strip()]
        matches.sort(key=lambda item: item.updated_at, reverse=True)
        return matches[: max(1, limit)]

    def list_pending_notifications(self) -> list[TelegramAgentTaskRecord]:
        terminal = {"success", "failed", "cancelled"}
        return [
            item
            for item in self.list_records()
            if item.status not in {"awaiting_confirmation"} and (item.status not in terminal or not item.notified)
        ]

    def create_record(
        self,
        *,
        chat_id: str,
        provider: str,
        preset: str,
        task_text: str,
        scope_path: str = "",
        job_id: str = "",
        status: str,
        confirmation_required: bool,
        task_id: str | None = None,
    ) -> TelegramAgentTaskRecord:
        now = utcnow_iso()
        record = TelegramAgentTaskRecord(
            task_id=task_id or str(uuid.uuid4()),
            chat_id=str(chat_id).strip(),
            provider=provider,
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
            status=status,
            created_at=now,
            updated_at=now,
            confirmation_required=confirmation_required,
        )
        return self.upsert(record)

    def _read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _write_all(self, records: list[TelegramAgentTaskRecord]) -> None:
        self.ensure_parent()
        payload = [asdict(item) for item in records]
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
