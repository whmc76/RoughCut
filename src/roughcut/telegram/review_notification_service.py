from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from roughcut.config import get_settings

_REVIEW_NOTIFICATION_MAX_ATTEMPTS = 8
_REVIEW_NOTIFICATION_LOCK_TIMEOUT_SECONDS = 5.0
_REVIEW_NOTIFICATION_LOCK_POLL_SECONDS = 0.05


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir_path() -> Path:
    settings = get_settings()
    state_dir = Path(str(getattr(settings, "telegram_agent_state_dir", "") or "").strip() or "data/telegram-agent")
    if not state_dir.is_absolute():
        state_dir = _repo_root() / state_dir
    return state_dir


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _retry_delay_seconds(attempt_count: int) -> int:
    normalized = max(1, int(attempt_count))
    return min(900, 30 * (2 ** min(normalized - 1, 4)))


def _next_retry_at_iso(attempt_count: int) -> str:
    return (_utcnow() + timedelta(seconds=_retry_delay_seconds(attempt_count))).isoformat()


def _build_notification_key(*, kind: str, job_id: str, force_full_review: bool) -> str:
    return f"{str(kind).strip()}:{str(job_id).strip()}:{1 if force_full_review else 0}"


@dataclass
class TelegramReviewNotificationRecord:
    notification_id: str
    notification_key: str
    kind: str
    job_id: str
    force_full_review: bool
    status: str
    created_at: str
    updated_at: str
    next_attempt_at: str
    attempt_count: int = 0
    last_error: str = ""
    delivered_at: str = ""


@dataclass
class TelegramReviewNotificationLoadResult:
    records: list[TelegramReviewNotificationRecord]
    read_error: str = ""


class TelegramReviewNotificationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def list_records(self, *, strict: bool = False) -> list[TelegramReviewNotificationRecord]:
        return self.load_records(strict=strict).records

    def load_records(self, *, strict: bool = False) -> TelegramReviewNotificationLoadResult:
        data, read_error = self._read_all(strict=strict)
        records: list[TelegramReviewNotificationRecord] = []
        invalid_messages: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                invalid_messages.append("store item is not an object")
                continue
            try:
                records.append(TelegramReviewNotificationRecord(**item))
            except TypeError as exc:
                invalid_messages.append(f"store item has invalid schema: {exc}")
                continue
        if invalid_messages:
            message = invalid_messages[0]
            if strict:
                raise RuntimeError(f"Review notification store is unreadable: {message}")
            read_error = message
        return TelegramReviewNotificationLoadResult(records=records, read_error=read_error)

    def get(self, notification_id: str, *, strict: bool = False) -> TelegramReviewNotificationRecord | None:
        normalized = str(notification_id).strip()
        for record in self.list_records(strict=strict):
            if record.notification_id == normalized:
                return record
        return None

    def get_by_key(self, notification_key: str, *, strict: bool = False) -> TelegramReviewNotificationRecord | None:
        normalized = str(notification_key).strip()
        for record in self.list_records(strict=strict):
            if record.notification_key == normalized:
                return record
        return None

    def upsert(self, record: TelegramReviewNotificationRecord) -> TelegramReviewNotificationRecord:
        with self._locked():
            records = self.list_records(strict=True)
            self._write_all(self._replace_or_insert(records, record))
        return record

    def due_records(self) -> list[TelegramReviewNotificationRecord]:
        return _due_records(self.list_records(strict=True))

    def create_or_requeue(
        self,
        *,
        kind: str,
        job_id: str,
        force_full_review: bool = False,
    ) -> TelegramReviewNotificationRecord:
        now = _utcnow_iso()
        key = _build_notification_key(kind=kind, job_id=job_id, force_full_review=force_full_review)
        with self._locked():
            records = self.list_records(strict=True)
            existing = next((item for item in records if item.notification_key == key), None)
            if existing is not None:
                existing.status = "pending"
                existing.force_full_review = bool(force_full_review)
                existing.attempt_count = 0
                existing.last_error = ""
                existing.delivered_at = ""
                existing.next_attempt_at = now
                existing.updated_at = now
                self._write_all(self._replace_or_insert(records, existing))
                return existing
            record = TelegramReviewNotificationRecord(
                notification_id=str(uuid.uuid4()),
                notification_key=key,
                kind=str(kind).strip(),
                job_id=str(job_id).strip(),
                force_full_review=bool(force_full_review),
                status="pending",
                created_at=now,
                updated_at=now,
                next_attempt_at=now,
            )
            self._write_all(self._replace_or_insert(records, record))
            return record

    def mark_delivered(self, notification_id: str) -> TelegramReviewNotificationRecord | None:
        with self._locked():
            records = self.list_records(strict=True)
            record = next((item for item in records if item.notification_id == str(notification_id).strip()), None)
            if record is None:
                return None
            now = _utcnow_iso()
            record.status = "delivered"
            record.updated_at = now
            record.delivered_at = now
            record.last_error = ""
            self._write_all(self._replace_or_insert(records, record))
            return record

    def mark_failed(self, notification_id: str, *, error_text: str) -> TelegramReviewNotificationRecord | None:
        with self._locked():
            records = self.list_records(strict=True)
            record = next((item for item in records if item.notification_id == str(notification_id).strip()), None)
            if record is None:
                return None
            record.status = "failed"
            record.updated_at = _utcnow_iso()
            record.last_error = str(error_text or "").strip()[:1200]
            self._write_all(self._replace_or_insert(records, record))
            return record

    def reschedule(self, notification_id: str, *, error_text: str) -> TelegramReviewNotificationRecord | None:
        with self._locked():
            records = self.list_records(strict=True)
            record = next((item for item in records if item.notification_id == str(notification_id).strip()), None)
            if record is None:
                return None
            record.attempt_count = max(0, int(record.attempt_count)) + 1
            record.last_error = str(error_text or "").strip()[:1200]
            record.updated_at = _utcnow_iso()
            if record.attempt_count >= _REVIEW_NOTIFICATION_MAX_ATTEMPTS:
                record.status = "failed"
                record.next_attempt_at = record.updated_at
            else:
                record.status = "pending"
                record.next_attempt_at = _next_retry_at_iso(record.attempt_count)
            self._write_all(self._replace_or_insert(records, record))
            return record

    def delete(self, notification_id: str) -> bool:
        normalized = str(notification_id).strip()
        with self._locked():
            records = self.list_records(strict=True)
            remaining = [item for item in records if item.notification_id != normalized]
            if len(remaining) == len(records):
                return False
            self._write_all(remaining)
            return True

    def _read_all(self, *, strict: bool = False) -> tuple[list[dict], str]:
        if not self._path.exists():
            return [], ""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            message = f"failed to read {self._path.name}: {exc}"
            if strict:
                raise RuntimeError(f"Review notification store is unreadable: {message}") from exc
            return [], message
        if not isinstance(data, list):
            message = f"failed to read {self._path.name}: root payload must be a list"
            if strict:
                raise RuntimeError(f"Review notification store is unreadable: {message}")
            return [], message
        return data, ""

    def _write_all(self, records: list[TelegramReviewNotificationRecord]) -> None:
        self.ensure_parent()
        payload = [asdict(item) for item in records]
        temp_path = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._path)

    def _replace_or_insert(
        self,
        records: list[TelegramReviewNotificationRecord],
        record: TelegramReviewNotificationRecord,
    ) -> list[TelegramReviewNotificationRecord]:
        replaced = False
        updated = list(records)
        for index, item in enumerate(updated):
            if item.notification_id == record.notification_id or item.notification_key == record.notification_key:
                updated[index] = record
                replaced = True
                break
        if not replaced:
            updated.insert(0, record)
        return updated[:200]

    def _lock_path(self) -> Path:
        return self._path.with_name(f"{self._path.name}.lock")

    @contextmanager
    def _locked(self):
        self.ensure_parent()
        lock_path = self._lock_path()
        deadline = time.monotonic() + _REVIEW_NOTIFICATION_LOCK_TIMEOUT_SECONDS
        handle: int | None = None
        while True:
            try:
                handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(handle, f"{os.getpid()} {time.time()}".encode("utf-8", errors="ignore"))
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out waiting for review notification store lock: {lock_path}")
                time.sleep(_REVIEW_NOTIFICATION_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            if handle is not None:
                os.close(handle)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def get_review_notification_store() -> TelegramReviewNotificationStore:
    return TelegramReviewNotificationStore(_state_dir_path() / "review_notifications.json")


def _normalize_status_filters(
    statuses: list[str] | tuple[str, ...] | None,
) -> set[str]:
    return {str(item).strip().lower() for item in statuses or [] if str(item).strip()}


def _filter_records(
    records: list[TelegramReviewNotificationRecord],
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int | None = None,
) -> list[TelegramReviewNotificationRecord]:
    filtered = list(records)
    allowed = _normalize_status_filters(statuses)
    if allowed:
        filtered = [item for item in filtered if str(item.status or "").strip().lower() in allowed]
    normalized_job_id = str(job_id or "").strip()
    if normalized_job_id:
        filtered = [item for item in filtered if str(item.job_id or "").strip() == normalized_job_id]
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind:
        filtered = [item for item in filtered if str(item.kind or "").strip().lower() == normalized_kind]
    if limit is not None:
        filtered = filtered[: max(1, int(limit))]
    return filtered


def _is_due_record(record: TelegramReviewNotificationRecord, *, now: datetime | None = None) -> bool:
    if str(record.status or "").strip().lower() != "pending":
        return False
    current = now or _utcnow()
    try:
        next_attempt_at = datetime.fromisoformat(str(record.next_attempt_at))
    except ValueError:
        next_attempt_at = current
    return next_attempt_at <= current


def _due_records(records: list[TelegramReviewNotificationRecord]) -> list[TelegramReviewNotificationRecord]:
    due = [item for item in records if _is_due_record(item)]
    due.sort(key=lambda item: (item.next_attempt_at, item.created_at))
    return due


def list_review_notifications(
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int | None = None,
) -> list[TelegramReviewNotificationRecord]:
    records = get_review_notification_store().list_records()
    return _filter_records(records, statuses=statuses, job_id=job_id, kind=kind, limit=limit)


def enqueue_review_notification(
    *,
    kind: str,
    job_id: str,
    force_full_review: bool = False,
) -> TelegramReviewNotificationRecord:
    return get_review_notification_store().create_or_requeue(
        kind=kind,
        job_id=job_id,
        force_full_review=force_full_review,
    )


def pending_review_notifications() -> list[TelegramReviewNotificationRecord]:
    return get_review_notification_store().due_records()


def requeue_review_notification(notification_id: str) -> TelegramReviewNotificationRecord | None:
    store = get_review_notification_store()
    with store._locked():
        record = store.get(notification_id, strict=True)
        if record is None:
            return None
        now = _utcnow_iso()
        record.status = "pending"
        record.attempt_count = 0
        record.last_error = ""
        record.delivered_at = ""
        record.next_attempt_at = now
        record.updated_at = now
        store._write_all(store._replace_or_insert(store.list_records(strict=True), record))
        return record


def requeue_review_notifications(notification_ids: list[str] | tuple[str, ...]) -> list[TelegramReviewNotificationRecord]:
    normalized_ids = [str(item).strip() for item in notification_ids if str(item).strip()]
    if not normalized_ids:
        return []
    store = get_review_notification_store()
    with store._locked():
        records = store.list_records(strict=True)
        record_map = {item.notification_id: item for item in records}
        updated_records: list[TelegramReviewNotificationRecord] = []
        now = _utcnow_iso()
        changed = False
        for notification_id in normalized_ids:
            record = record_map.get(notification_id)
            if record is None:
                continue
            record.status = "pending"
            record.attempt_count = 0
            record.last_error = ""
            record.delivered_at = ""
            record.next_attempt_at = now
            record.updated_at = now
            updated_records.append(record)
            changed = True
        if changed:
            store._write_all(records[:200])
        return updated_records


def drop_review_notification(notification_id: str) -> bool:
    return get_review_notification_store().delete(notification_id)


def drop_review_notifications(notification_ids: list[str] | tuple[str, ...]) -> list[str]:
    normalized_ids = {str(item).strip() for item in notification_ids if str(item).strip()}
    if not normalized_ids:
        return []
    store = get_review_notification_store()
    with store._locked():
        records = store.list_records(strict=True)
        remaining = [item for item in records if item.notification_id not in normalized_ids]
        dropped_ids = [item.notification_id for item in records if item.notification_id in normalized_ids]
        if dropped_ids:
            store._write_all(remaining)
        return dropped_ids


def mark_review_notification_delivered(notification_id: str) -> TelegramReviewNotificationRecord | None:
    return get_review_notification_store().mark_delivered(notification_id)


def mark_review_notification_failed(notification_id: str, *, error_text: str) -> TelegramReviewNotificationRecord | None:
    return get_review_notification_store().mark_failed(notification_id, error_text=error_text)


def reschedule_review_notification(notification_id: str, *, error_text: str) -> TelegramReviewNotificationRecord | None:
    return get_review_notification_store().reschedule(notification_id, error_text=error_text)


def build_review_notification_snapshot(
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict[str, object]:
    store = get_review_notification_store()
    load_result = store.load_records()
    records = _filter_records(load_result.records, statuses=statuses, job_id=job_id, kind=kind)
    limited_records = _filter_records(records, limit=limit)
    due_ids = {item.notification_id for item in _due_records(records)}
    summary = {
        "total": len(records),
        "pending": sum(1 for item in records if item.status == "pending"),
        "due_now": sum(1 for item in records if item.notification_id in due_ids),
        "failed": sum(1 for item in records if item.status == "failed"),
        "delivered": sum(1 for item in records if item.status == "delivered"),
    }
    items = [
        {
            "notification_id": item.notification_id,
            "kind": item.kind,
            "job_id": item.job_id,
            "status": item.status,
            "attempt_count": item.attempt_count,
            "next_attempt_at": item.next_attempt_at,
            "last_error": item.last_error,
            "force_full_review": item.force_full_review,
            "updated_at": item.updated_at,
        }
        for item in limited_records
    ]
    detail = load_result.read_error.strip()
    if not detail:
        detail = f"{len(records)} queued notifications"
    return {
        "state_dir": str(_state_dir_path()),
        "store_file": str(store._path),
        "detail": detail,
        "summary": summary,
        "items": items,
    }
