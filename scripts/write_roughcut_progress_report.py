from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


API_CANDIDATES = [
    os.environ.get("ROUGHCUT_API_BASE", "").strip(),
    "http://127.0.0.1:8001/api/v1",
    "http://127.0.0.1:8000/api/v1",
]
REPORT_PATH = Path(r"Y:\EDC系列\AI粗剪\roughcut_progress_report.md")
SNAPSHOT_PATH = Path(r"Y:\EDC系列\AI粗剪\roughcut_progress_report.json")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
STALE_MINUTES = 20


def _http_json(url: str) -> Any:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_api_base() -> str:
    errors: list[str] = []
    for candidate in API_CANDIDATES:
        base = str(candidate or "").strip().rstrip("/")
        if not base:
            continue
        try:
            _http_json(base.replace("/api/v1", "") + "/health")
            return base
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{base}: {exc}")
    raise RuntimeError("No reachable RoughCut API base. " + " | ".join(errors))


def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _fmt_dt(value: str | None) -> str:
    parsed = _parse_dt(value)
    if parsed is None:
        return "-"
    return parsed.astimezone().strftime(TIME_FORMAT)


def _step_sort_key(step: dict[str, Any]) -> tuple[int, str]:
    status = str(step.get("status") or "")
    priority = {
        "failed": 0,
        "running": 1,
        "processing": 1,
        "pending": 2,
        "done": 3,
        "skipped": 4,
    }.get(status, 5)
    return (priority, str(step.get("step_name") or ""))


def _job_title(job: dict[str, Any]) -> str:
    merged = list(job.get("merged_source_names") or [])
    if merged:
        return " / ".join(merged)
    return str(job.get("source_name") or job.get("id") or "unknown")


def _running_step(job: dict[str, Any]) -> dict[str, Any] | None:
    for step in sorted(list(job.get("steps") or []), key=_step_sort_key):
        if str(step.get("status")) == "running":
            return step
    return None


def _collect_failed_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in list(job.get("steps") or []) if str(step.get("status")) == "failed"]


def _is_stale_running(job: dict[str, Any]) -> bool:
    step = _running_step(job)
    started_at = _parse_dt(step.get("started_at") if step else None)
    if started_at is None:
        return False
    return datetime.now(started_at.tzinfo) - started_at >= timedelta(minutes=STALE_MINUTES)


@dataclass
class JobInsight:
    job: dict[str, Any]
    activity: dict[str, Any] | None
    report: dict[str, Any] | None
    content_profile: dict[str, Any] | None
    issues: list[str]


def _fetch_job_insight(api_base: str, job: dict[str, Any]) -> JobInsight:
    job_id = str(job.get("id"))
    issues: list[str] = []

    activity = None
    report = None
    content_profile = None

    try:
        activity = _http_json(f"{api_base}/jobs/{job_id}/activity")
    except Exception as exc:  # pragma: no cover - diagnostic best effort
        issues.append(f"活动信息读取失败: {exc}")

    try:
        report = _http_json(f"{api_base}/jobs/{job_id}/report")
    except Exception:
        report = None

    try:
        content_profile = _http_json(f"{api_base}/jobs/{job_id}/content-profile")
    except Exception:
        content_profile = None

    error_message = str(job.get("error_message") or "").strip()
    if error_message:
        issues.append(f"任务错误: {error_message}")

    for step in _collect_failed_steps(job):
        detail = str(step.get("error_message") or "").strip()
        issues.append(f"步骤失败: {step.get('step_name')}" + (f" | {detail}" if detail else ""))

    if _is_stale_running(job):
        step = _running_step(job)
        issues.append(f"步骤疑似卡住: {step.get('step_name')} 已运行超过 {STALE_MINUTES} 分钟")

    if report is not None:
        subtitle_count = int(report.get("total_subtitle_items") or 0)
        if subtitle_count == 0:
            transcribe_done = any(
                str(step.get("step_name")) == "transcribe" and str(step.get("status")) == "done"
                for step in list(job.get("steps") or [])
            )
            if transcribe_done:
                issues.append("字幕风险: 转写已完成，但报告中的字幕条数为 0")
        pending_count = int(report.get("pending_count") or 0)
        if pending_count > 0:
            issues.append(f"人工审核待处理: {pending_count} 条")

    if content_profile is not None:
        if str(content_profile.get("status") or "") == "needs_review":
            reasons = list(content_profile.get("review_reasons") or [])
            issues.append("内容画像待审: " + ("；".join(map(str, reasons[:4])) if reasons else "需要人工确认"))
        blocking = list(content_profile.get("blocking_reasons") or [])
        if blocking:
            issues.append("内容画像阻塞: " + "；".join(map(str, blocking[:4])))

    if activity is not None:
        for decision in list(activity.get("decisions") or []):
            if str(decision.get("status")) == "failed":
                issues.append(f"增强失败: {decision.get('title')} | {decision.get('summary')}")

    quality_score = job.get("quality_score")
    if quality_score is not None and float(quality_score) < 80:
        issues.append(f"质量分偏低: {quality_score}")

    return JobInsight(job=job, activity=activity, report=report, content_profile=content_profile, issues=issues)


def _status_summary(jobs: list[dict[str, Any]]) -> Counter:
    counter: Counter[str] = Counter()
    for job in jobs:
        counter[str(job.get("status") or "unknown")] += 1
    return counter


def _render_markdown(api_base: str, insights: list[JobInsight]) -> str:
    now = datetime.now().strftime(TIME_FORMAT)
    jobs = [item.job for item in insights]
    counts = _status_summary(jobs)

    lines: list[str] = []
    lines.append(f"# RoughCut Progress Report")
    lines.append("")
    lines.append(f"- Updated: {now}")
    lines.append(f"- API: `{api_base}`")
    lines.append(f"- Total jobs: {len(jobs)}")
    lines.append(
        "- Status summary: "
        + ", ".join(f"{key}={counts[key]}" for key in sorted(counts.keys()))
    )
    lines.append("")

    attention = [item for item in insights if item.issues]
    lines.append("## Attention")
    if not attention:
        lines.append("- No blocking issues detected.")
    else:
        for item in attention:
            lines.append(f"- {_job_title(item.job)}")
            for issue in item.issues:
                lines.append(f"  - {issue}")
    lines.append("")

    lines.append("## Jobs")
    for item in insights:
        job = item.job
        running = _running_step(job)
        current_step = str(running.get("step_name")) if running else str((item.activity or {}).get("current_step", {}).get("step_name") or "-")
        subtitle_count = None
        if item.report is not None:
            subtitle_count = int(item.report.get("total_subtitle_items") or 0)
        lines.append(f"### {_job_title(job)}")
        lines.append(f"- Job ID: `{job.get('id')}`")
        lines.append(f"- Status: `{job.get('status')}`")
        lines.append(f"- Current step: `{current_step}`")
        lines.append(f"- Progress: `{job.get('progress_percent', 0)}%`")
        lines.append(f"- Workflow template: `{job.get('workflow_template')}`")
        lines.append(f"- Updated: {_fmt_dt(job.get('updated_at'))}")
        if subtitle_count is not None:
            lines.append(f"- Subtitle items: `{subtitle_count}`")
        if item.content_profile is not None:
            lines.append(f"- Content-profile status: `{item.content_profile.get('status')}`")
        if item.issues:
            lines.append(f"- Issues: {' | '.join(item.issues[:4])}")
        else:
            lines.append("- Issues: none detected")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    api_base = _resolve_api_base()
    jobs = _http_json(f"{api_base}/jobs")
    insights = [_fetch_job_insight(api_base, job) for job in jobs]
    markdown = _render_markdown(api_base, insights)
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    SNAPSHOT_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().isoformat(),
                "api_base": api_base,
                "jobs": [item.job for item in insights],
                "issues": {str(item.job.get('id')): item.issues for item in insights if item.issues},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(str(REPORT_PATH))


if __name__ == "__main__":
    main()
