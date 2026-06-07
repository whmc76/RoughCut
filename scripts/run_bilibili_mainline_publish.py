from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.publication_mainline import (
    build_platform_mainline_browser_agent_task,
    default_profiles_json_path,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    with request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _poll_task(browser_agent_base_url: str, task_id: str, timeout_seconds: int, poll_interval: int) -> dict:
    deadline = time.time() + timeout_seconds
    last: dict = {}
    while time.time() < deadline:
        payload = _get_json(f"{browser_agent_base_url.rstrip('/')}/tasks/{task_id}")
        task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
        last = task if isinstance(task, dict) else {}
        status = str(last.get("status") or "").strip().lower()
        if status and status not in {"queued", "processing", "submitted"}:
            return payload
        time.sleep(max(1, poll_interval))
    return {"task": last, "timeout": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Bilibili mainline publication task directly.")
    parser.add_argument("--target-profile-id", required=True)
    parser.add_argument("--material-json", required=True)
    parser.add_argument("--media-path", required=True)
    parser.add_argument("--profiles-json", default=str(default_profiles_json_path()))
    parser.add_argument("--browser-agent-base-url", default="http://127.0.0.1:49310")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--output", required=True)
    parser.add_argument("--current-page-only", action="store_true")
    parser.add_argument("--stop-before-final-publish", action="store_true")
    parser.add_argument("--collection-name", default="")
    parser.add_argument("--scheduled-publish-at", default="")
    parser.add_argument("--title-override", default="")
    parser.add_argument("--body-override", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--browser", default="")
    parser.add_argument("--browser-user-data-dir", default="")
    parser.add_argument("--browser-profile-directory", default="")
    parser.add_argument("--browser-profile-name", default="")
    parser.add_argument("--browser-profile-email", default="")
    parser.add_argument("--browser-cdp-base-url", default="")
    parser.add_argument("--account-label", default="")
    parser.add_argument("--credential-ref", default="")
    args = parser.parse_args()

    platform_packaging = _load_json(Path(args.material_json))
    profiles_payload = _load_json(Path(args.profiles_json))
    browser_binding_override = None
    if any(
        str(value or "").strip()
        for value in (
            args.browser,
            args.browser_user_data_dir,
            args.browser_profile_directory,
            args.browser_profile_name,
            args.browser_profile_email,
            args.browser_cdp_base_url,
        )
    ):
        browser_binding_override = {
            "browser": str(args.browser or "").strip(),
            "user_data_dir": str(args.browser_user_data_dir or "").strip(),
            "profile_directory": str(args.browser_profile_directory or "").strip(),
            "profile_name": str(args.browser_profile_name or "").strip(),
            "profile_email": str(args.browser_profile_email or "").strip(),
            "cdp_base_url": str(args.browser_cdp_base_url or "").strip(),
        }
    task_payload = build_platform_mainline_browser_agent_task(
        creator_profile_id=args.target_profile_id,
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=args.media_path,
        current_page_only=bool(args.current_page_only),
        stop_before_final_publish=bool(args.stop_before_final_publish),
        collection_override=str(args.collection_name or "").strip() or None,
        scheduled_publish_at_override=str(args.scheduled_publish_at or "").strip() or None,
        title_override=str(args.title_override or "").strip() or None,
        body_override=str(args.body_override or "").strip() or None,
        browser_binding_override=browser_binding_override,
        account_label_override=str(args.account_label or "").strip() or None,
        credential_ref_override=str(args.credential_ref or "").strip() or None,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        output_path.write_text(json.dumps({"task_payload": task_payload}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    started = _post_json(f"{args.browser_agent_base_url.rstrip('/')}/tasks", task_payload)
    task = started.get("task") if isinstance(started.get("task"), dict) else {}
    task_id = str(task.get("task_id") or task.get("id") or task_payload.get("task_id") or "").strip()
    if not task_id:
        output_path.write_text(json.dumps({"started": started}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("browser-agent did not return task_id")
    result = _poll_task(args.browser_agent_base_url, task_id, args.timeout_seconds, args.poll_interval)
    output_path.write_text(
        json.dumps({"task_payload": task_payload, "started": started, "result": result}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
