from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from roughcut.api import review as review_api
from roughcut.watcher import folder_watcher


def test_get_watch_root_inventory_scan_status_marks_orphaned_running_state_failed(monkeypatch) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = folder_watcher.WatchInventoryScanState(
        root_path="Z:/watch/demo",
        scan_mode="fast",
        status="running",
        started_at=(now - timedelta(seconds=90)).isoformat(),
        updated_at=(now - timedelta(seconds=90)).isoformat(),
        finished_at=None,
        total_files=10,
        processed_files=3,
        pending_count=2,
        deduped_count=1,
        current_file="demo.mp4",
        current_phase="hashing",
        current_file_size_bytes=100,
        current_file_processed_bytes=40,
        error=None,
        pending=[],
        deduped=[],
    )
    monkeypatch.setattr(folder_watcher, "_SCAN_STATES", {"Z:/watch/demo": state})
    monkeypatch.setattr(folder_watcher, "_SCAN_TASKS", {})

    payload = folder_watcher.get_watch_root_inventory_scan_status("Z:/watch/demo", include_inventory=False)

    assert payload is not None
    assert payload["status"] == "failed"
    assert payload["error"] == "目录扫描已中断，请重新扫描。"
    assert payload["current_file"] is None


def test_cached_status_payload_recovers_persisted_running_snapshot() -> None:
    stale = (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=90)).isoformat()
    root = SimpleNamespace(
        path="Z:/watch/demo",
        scan_mode="fast",
        inventory_cache_json={
            "status": "running",
            "started_at": stale,
            "updated_at": stale,
            "pending_count": 1,
            "deduped_count": 0,
            "current_file": "demo.mp4",
            "current_phase": "hashing",
            "inventory": {"pending": [{"path": "demo.mp4"}], "deduped": []},
        },
    )

    payload = review_api._cached_status_payload(root, include_inventory=False, inventory_limit=50)

    assert payload["status"] == "failed"
    assert payload["error"] == "目录扫描已中断，请重新扫描。"
    assert payload["inventory"] == {"pending": [], "deduped": []}
