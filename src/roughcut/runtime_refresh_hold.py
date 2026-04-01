from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_HOLD_SECONDS = 90


def get_runtime_refresh_hold_path() -> Path:
    override = str(os.getenv("ROUGHCUT_RUNTIME_REFRESH_HOLD_PATH", "") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.cwd() / "logs" / "runtime-refresh-hold.json"


def touch_runtime_refresh_hold(
    *,
    reason: str,
    job_id: str | None = None,
    hold_seconds: int = _DEFAULT_HOLD_SECONDS,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(15, int(hold_seconds or _DEFAULT_HOLD_SECONDS)))
    payload: dict[str, Any] = {
        "reason": str(reason or "runtime_interaction").strip() or "runtime_interaction",
        "job_id": str(job_id or "").strip() or None,
        "touched_at_utc": now.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": expires_at.isoformat().replace("+00:00", "Z"),
    }
    if details:
        payload["details"] = dict(details)

    hold_path = get_runtime_refresh_hold_path()
    hold_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = hold_path.with_suffix(f"{hold_path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(hold_path)
    return payload


def load_active_runtime_refresh_hold(*, now: datetime | None = None) -> dict[str, Any] | None:
    hold_path = get_runtime_refresh_hold_path()
    if not hold_path.exists():
        return None

    try:
        payload = json.loads(hold_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    expires_raw = str(payload.get("expires_at_utc") or "").strip()
    if not expires_raw:
        return None

    try:
        expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    current_time = now or datetime.now(timezone.utc)
    if expires_at <= current_time:
        return None
    return payload
