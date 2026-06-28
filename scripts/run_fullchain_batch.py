from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import concurrent.futures
import threading
import os
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import delete, select

from roughcut.config import get_settings
from roughcut.creative.modes import resolve_live_batch_enhancement_modes
from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import get_session_factory, reset_session_state_sync
from roughcut.pipeline.orchestrator import MAX_ATTEMPTS, PIPELINE_STEPS
from roughcut.pipeline.render_diagnostics import (
    classify_avatar_runtime_reason_category as _shared_classify_avatar_runtime_reason_category,
    classify_render_failure_reason as _shared_classify_render_failure_reason,
    normalize_render_step_summary_for_reporting as _shared_normalize_render_step_summary_for_reporting,
)
from roughcut.pipeline.live_readiness import build_live_readiness_summary
from roughcut.pipeline.quality import assess_job_quality
from roughcut.pipeline.steps import run_step_sync
from roughcut.runtime_health import build_readiness_payload
from roughcut.edit.refine_decisions import resolve_refine_keep_segments_for_timeline
from roughcut.review.downstream_context import strip_publication_only_profile_fields
from roughcut.review.subtitle_consistency import ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT
from roughcut.review.subtitle_term_resolution import ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER
from roughcut.speech.transcribe import ARTIFACT_TYPE_ASR_QUALITY_GATE
from roughcut.watcher.folder_watcher import _create_job_for_file, create_jobs_for_inventory_paths

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
_BATCH_STEP_TIMEOUT_SECONDS = 1800.0
_BATCH_STEP_TIMEOUT_MIN_SECONDS = 1.0
_BATCH_STEP_TIMEOUT_SECONDS_BY_STEP = {
    "content_profile": 420.0,
    "render": 5400.0,
}
_BATCH_STEP_TIMEOUT_STRATEGY = "thread"
_BATCH_STEP_TIMEOUT_STRATEGY_BY_STEP = {
    "content_profile": "process",
    "render": "process",
}
_BATCH_STEP_TIMEOUT_STRATEGIES = {"thread", "process"}


def _configure_console_encoding() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _is_windows_proactor_closed_pipe_unraisable(unraisable: Any) -> bool:
    if sys.platform != "win32":
        return False
    exc_type = getattr(unraisable, "exc_type", None)
    exc_value = getattr(unraisable, "exc_value", None)
    if exc_type is not ValueError or "closed pipe" not in str(exc_value):
        return False
    traceback_obj = getattr(unraisable, "exc_traceback", None)
    while traceback_obj is not None:
        filename = str(getattr(traceback_obj.tb_frame.f_code, "co_filename", "") or "").replace("\\", "/")
        if filename.endswith("/asyncio/proactor_events.py") or filename.endswith("/asyncio/base_subprocess.py"):
            return True
        traceback_obj = traceback_obj.tb_next
    return False


def _configure_windows_proactor_unraisable_filter() -> None:
    previous_hook = sys.unraisablehook

    def hook(unraisable: Any) -> None:
        if _is_windows_proactor_closed_pipe_unraisable(unraisable):
            return
        previous_hook(unraisable)

    sys.unraisablehook = hook


def _resolve_batch_step_timeout_seconds(step_name: str) -> float:
    default_timeout_seconds = _BATCH_STEP_TIMEOUT_SECONDS
    default_raw = str(os.getenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS", "")).strip()
    if default_raw:
        try:
            default_timeout_seconds = float(default_raw)
        except ValueError:
            default_timeout_seconds = _BATCH_STEP_TIMEOUT_SECONDS
    normalized_step = str(step_name or "").strip().lower()
    step_timeout_seconds = _BATCH_STEP_TIMEOUT_SECONDS_BY_STEP.get(normalized_step, default_timeout_seconds)
    if normalized_step == "render":
        settings = get_settings()
        step_timeout_seconds = max(
            float(step_timeout_seconds),
            float(getattr(settings, "render_step_stale_timeout_sec", 5400) or 5400),
        )
    if default_raw:
        step_timeout_seconds = default_timeout_seconds
    step_override_env = f"ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_{normalized_step.upper()}"
    step_override_raw = str(os.getenv(step_override_env, "")).strip()
    if step_override_raw:
        try:
            step_timeout_seconds = float(step_override_raw)
        except ValueError:
            pass
    return max(_BATCH_STEP_TIMEOUT_MIN_SECONDS, float(step_timeout_seconds))


def _apply_terminal_status_to_quality_assessment(
    quality_assessment: dict[str, Any] | None,
    *,
    status: str,
    render_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(quality_assessment or {})
    if status == "done":
        return payload

    issue_codes = [str(code) for code in list(payload.get("issue_codes") or []) if str(code).strip()]
    if status == "failed":
        issue_codes.append("job_failed")
        render_step = (
            dict(render_diagnostics.get("render_step") or {})
            if isinstance(render_diagnostics, dict) and isinstance(render_diagnostics.get("render_step"), dict)
            else {}
        )
        if render_step:
            _, render_issue_codes = _classify_render_failure_reason(
                error=str(render_step.get("error") or ""),
                detail=str(render_step.get("detail") or ""),
                sync_runner=dict(render_step.get("sync_runner") or {})
                if isinstance(render_step.get("sync_runner"), dict)
                else None,
            )
            issue_codes.extend(render_issue_codes or ["render_failed"])
        payload["score"] = 0.0
        payload["grade"] = "E"
    elif status == "partial":
        issue_codes.append("partial_run")
        if payload.get("score") is not None:
            payload["score"] = min(float(payload.get("score") or 0.0), 60.0)
            payload["grade"] = "D" if float(payload["score"]) < 60.0 else "C"
    payload["issue_codes"] = sorted(set(issue_codes))
    return payload


def _run_step_sync_with_timeout(step_name: str, job_id: str, timeout_seconds: float) -> None:
    if timeout_seconds <= 0:
        run_step_sync(step_name, job_id)
        return

    strategy = _resolve_batch_step_timeout_strategy(step_name)
    if strategy == "process":
        _run_step_sync_with_timeout_in_process(step_name, job_id, timeout_seconds)
    else:
        _run_step_sync_with_timeout_in_thread(step_name, job_id, timeout_seconds)


def _resolve_batch_step_timeout_strategy(step_name: str) -> str:
    normalized_step = str(step_name or "").strip().lower()
    strategy_raw = str(os.getenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY", _BATCH_STEP_TIMEOUT_STRATEGY)).strip().lower()
    if strategy_raw not in _BATCH_STEP_TIMEOUT_STRATEGIES:
        strategy_raw = _BATCH_STEP_TIMEOUT_STRATEGY

    strategy = _BATCH_STEP_TIMEOUT_STRATEGY_BY_STEP.get(normalized_step, strategy_raw)
    if strategy not in _BATCH_STEP_TIMEOUT_STRATEGIES:
        return _BATCH_STEP_TIMEOUT_STRATEGY

    step_strategy = str(os.getenv(f"ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_{normalized_step.upper()}", "")).strip().lower()
    if step_strategy in _BATCH_STEP_TIMEOUT_STRATEGIES:
        return step_strategy
    return strategy


def _run_step_sync_with_timeout_in_thread(step_name: str, job_id: str, timeout_seconds: float) -> None:
    error_holder: list[BaseException] = []

    def _runner() -> None:
        try:
            run_step_sync(step_name, job_id)
        except BaseException as exc:
            error_holder.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        exc = TimeoutError(f"步骤 {step_name} 执行超过 {float(timeout_seconds):.1f} 秒")
        setattr(
            exc,
            "__batch_step_execution_metadata__",
            {
                "sync_runner_timeout_strategy": "thread",
                "sync_runner_timeout_seconds": float(timeout_seconds),
                "sync_runner_step_name": str(step_name).strip().lower(),
            },
        )
        raise exc
    if error_holder:
        exc = error_holder[0]
        raise exc


def _run_step_sync_process_worker(step_name: str, job_id: str, result_queue: multiprocessing.Queue) -> None:
    import traceback

    try:
        run_step_sync(step_name, job_id)
        result_queue.put({"status": "ok"})
    except BaseException as exc:
        result_queue.put(
            {
                "status": "error",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        reset_session_state_sync()


def _run_step_sync_with_timeout_in_process(step_name: str, job_id: str, timeout_seconds: float) -> None:
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue = ctx.Queue()
    process = ctx.Process(target=_run_step_sync_process_worker, args=(step_name, job_id, result_queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        worker_pid = process.pid
        process.terminate()
        process.join(5)
        reap_method = "terminate"
        if process.is_alive():
            process.kill()
            process.join(1)
            reap_method = "kill"
        metadata = {
            "sync_runner_timeout_strategy": "process",
            "sync_runner_timeout_seconds": float(timeout_seconds),
            "sync_runner_step_name": str(step_name).strip().lower(),
            "sync_runner_worker_pid": worker_pid,
            "sync_runner_reap_method": reap_method,
            "sync_runner_process_exit_code": process.exitcode,
        }
        exc = TimeoutError(f"步骤 {step_name} 执行超过 {float(timeout_seconds):.1f} 秒")
        setattr(exc, "__batch_step_execution_metadata__", metadata)
        raise exc

    try:
        payload = result_queue.get_nowait()
    except Exception:
        payload = None

    if process.exitcode == 0:
        if payload and payload.get("status") == "ok":
            return
        if payload and payload.get("status") == "error":
            exc = RuntimeError(f"{payload.get('type')}: {payload.get('message')}")
            setattr(exc, "__batch_worker_traceback__", payload.get("traceback"))
            setattr(
                exc,
                "__batch_step_execution_metadata__",
                {
                    "sync_runner_timeout_strategy": "process",
                    "sync_runner_step_name": str(step_name).strip().lower(),
                    "sync_runner_process_exit_code": process.exitcode,
                },
            )
            raise exc
        raise RuntimeError(f"步骤 {step_name} 执行结果无效（exit=0）")

    if payload and payload.get("status") == "error":
        exc = RuntimeError(f"{payload.get('type')}: {payload.get('message')}")
        setattr(exc, "__batch_worker_traceback__", payload.get("traceback"))
        setattr(
            exc,
            "__batch_step_execution_metadata__",
            {
                "sync_runner_timeout_strategy": "process",
                "sync_runner_step_name": str(step_name).strip().lower(),
                "sync_runner_process_exit_code": process.exitcode,
            },
        )
        raise exc
    exc = RuntimeError(f"步骤 {step_name} 子进程异常退出: exit_code={process.exitcode}")
    setattr(
        exc,
        "__batch_step_execution_metadata__",
        {
            "sync_runner_timeout_strategy": "process",
            "sync_runner_step_name": str(step_name).strip().lower(),
            "sync_runner_process_exit_code": process.exitcode,
        },
    )
    raise exc


def _configure_local_event_loop_policy() -> None:
    # Selector loops do not support asyncio subprocess APIs used by render (ffmpeg
    # execution path). Keep default Proactor behavior unless explicitly forced.
    #
    # Set ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP=1 only when reproducing known
    # Windows asyncpg-specific noise in environments that never require subprocess.
    force_selector = str(os.getenv("ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP", "")).strip().lower() in {"1", "true", "yes", "on"}
    if not force_selector:
        return

    # asyncpg on Windows can emit Proactor InvalidStateError noise when this script
    # repeatedly opens and tears down short-lived event loops via asyncio.run().
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:
        return
    asyncio.set_event_loop_policy(policy_cls())


def get_legacy_cover_manifest_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_cover_variants.json")


@dataclass
class StepRun:
    step: str
    status: str
    elapsed_seconds: float
    detail: str = ""
    error: str = ""


@dataclass
class LiveStageValidation:
    stage: str
    status: str
    summary: str
    issue_codes: list[str] = field(default_factory=list)


@dataclass
class JobRunReport:
    job_id: str
    source_path: str
    source_name: str
    status: str
    output_path: str | None
    cover_path: str | None
    output_duration_sec: float
    transcript_segment_count: int
    subtitle_count: int
    correction_count: int
    keep_ratio: float
    cover_variant_count: int
    platform_doc: str | None
    quality_score: float | None
    quality_grade: str | None
    quality_issue_codes: list[str]
    live_stage_validations: list[LiveStageValidation]
    content_profile: dict[str, Any] | None
    steps: list[StepRun]
    notes: list[str]
    asr_evidence: dict[str, Any] = field(default_factory=dict)
    step_sync_runner_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    render_diagnostics: dict[str, Any] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full-chain ROUGHCUT batch on unedited local videos.")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "watch")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--channel-profile", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--scan-mode", choices=["fast", "precise"], default="fast")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / "fullchain-batch")
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=1,
        help="Number of source videos to run concurrently",
    )
    parser.add_argument(
        "--stop-after",
        choices=PIPELINE_STEPS,
        default=None,
        help="Stop after the specified step and still collect a partial report",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--enhancement-mode",
        dest="enhancement_modes",
        action="append",
        default=[],
        help="Repeatable enhancement mode override",
    )
    parser.add_argument(
        "--source-name",
        dest="source_names",
        action="append",
        default=[],
        help="Repeatable exact source filename filter",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Optional JSON array or newline-delimited text file of exact source filenames to run",
    )
    parser.add_argument(
        "--pollution-audit",
        type=Path,
        default=None,
        help="Optional subtitle_pollution_audit.json used to derive exact source filenames",
    )
    parser.add_argument(
        "--manual-review-only",
        action="store_true",
        help="When used with --pollution-audit, only rerun jobs marked manual_review_required",
    )
    parser.add_argument(
        "--force-rerun-existing",
        action="store_true",
        help="Reset and rerun matching jobs even if a finished render already exists",
    )
    parser.add_argument(
        "--fresh-jobs",
        action="store_true",
        help="Always create new jobs for this batch instead of reusing matching source-name jobs.",
    )
    parser.add_argument(
        "--golden-manifest",
        type=Path,
        default=None,
        help="Optional JSON array or newline-delimited text file of golden source names",
    )
    parser.add_argument(
        "--previous-batch-report",
        dest="previous_batch_reports",
        action="append",
        default=[],
        help="Repeatable prior batch_report.json path used to evaluate consecutive stable runs",
    )
    return parser.parse_args()


def main() -> None:
    _configure_console_encoding()
    _configure_windows_proactor_unraisable_filter()
    _configure_local_event_loop_policy()
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    ensure_batch_runtime_ready()
    parallel_jobs = max(1, int(args.parallel_jobs or 1))
    enhancement_modes = resolve_live_batch_enhancement_modes(args.enhancement_modes)
    target_source_names = resolve_target_source_names(
        explicit_source_names=args.source_names,
        source_manifest=args.source_manifest,
        pollution_audit=args.pollution_audit,
        manual_review_only=args.manual_review_only,
    )

    print(f"[batch] scanning source files {args.source_dir}", flush=True)
    source_items = select_source_candidates(
        args.source_dir,
        max(args.limit * 4, args.limit),
        source_names=target_source_names,
    )
    if not source_items:
        raise SystemExit("No source videos found.")
    print(f"[batch] candidate sources {len(source_items)}", flush=True)

    target_items = source_items[: args.limit]
    prepared_jobs: list[dict[str, Any]] = []
    reports: list[JobRunReport] = []
    for item in target_items:
        write_batch_progress(
            report_dir=args.report_dir,
            source_dir=args.source_dir,
            channel_profile=args.channel_profile,
            language=args.language,
            output_dir=args.output_dir,
            enhancement_modes=enhancement_modes,
            reports=reports,
            current_item=item,
            queued_items=[pending["item"] for pending in prepared_jobs],
            status="preparing",
        )
        job_id = asyncio.run(
            prepare_job_for_source(
                Path(item["path"]),
                channel_profile=args.channel_profile,
                language=args.language,
                output_dir=args.output_dir,
                enhancement_modes=enhancement_modes,
                force_rerun_existing=args.force_rerun_existing,
                fresh_jobs=args.fresh_jobs,
            )
        )
        if not job_id:
            continue
        prepared_jobs.append({"job_id": job_id, "item": item})

    if not prepared_jobs:
        raise SystemExit("No jobs were created from the pending inventory.")

    order_index = {entry["item"]["source_name"]: index for index, entry in enumerate(prepared_jobs)}
    pending_jobs = list(prepared_jobs)
    active_futures: dict[concurrent.futures.Future[JobRunReport], dict[str, Any]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
        while pending_jobs or active_futures:
            while pending_jobs and len(active_futures) < parallel_jobs:
                entry = pending_jobs.pop(0)
                item = entry["item"]
                job_id = entry["job_id"]
                print(f"[batch] running {item.get('source_name')} job={job_id}", flush=True)
                future = executor.submit(run_job, job_id, item, stop_after=args.stop_after)
                active_futures[future] = entry

            running_entries = [entry for entry in active_futures.values()]
            write_batch_progress(
                report_dir=args.report_dir,
                source_dir=args.source_dir,
                channel_profile=args.channel_profile,
                language=args.language,
                output_dir=args.output_dir,
                enhancement_modes=enhancement_modes,
                reports=reports,
                running_jobs=running_entries,
                queued_items=[entry["item"] for entry in pending_jobs],
                status="running",
            )
            if not active_futures:
                break

            done_futures, _ = concurrent.futures.wait(
                active_futures.keys(),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done_futures:
                entry = active_futures.pop(future)
                report = future.result()
                reports.append(report)
                reports.sort(key=lambda item: order_index.get(item.source_name, 999999))
                write_batch_progress(
                    report_dir=args.report_dir,
                    source_dir=args.source_dir,
                    channel_profile=args.channel_profile,
                    language=args.language,
                    output_dir=args.output_dir,
                    enhancement_modes=enhancement_modes,
                    reports=reports,
                    running_jobs=[item for item in active_futures.values()],
                    queued_items=[item["item"] for item in pending_jobs],
                    status="running",
                )

    if not reports:
        raise SystemExit("No jobs completed in the batch run.")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "channel_profile": args.channel_profile,
        "language": args.language,
        "output_dir": args.output_dir,
        "stop_after": args.stop_after,
        "enhancement_modes": enhancement_modes,
        "job_count": len(reports),
        "success_count": sum(1 for report in reports if report.status == "done"),
        "partial_count": sum(1 for report in reports if report.status == "partial"),
        "failed_count": sum(1 for report in reports if report.status == "failed"),
        "jobs": [asdict(report) for report in reports],
    }
    golden_source_names = resolve_golden_source_names(
        source_names=target_source_names,
        golden_manifest=args.golden_manifest,
    )
    previous_summaries = load_previous_batch_summaries(args.previous_batch_reports)
    live_readiness = asdict(
        build_live_readiness_summary(
            summary,
            golden_source_names=golden_source_names,
            previous_summaries=previous_summaries,
        )
    )
    summary["live_readiness"] = live_readiness
    (args.report_dir / "batch_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.report_dir / "batch_report.md").write_text(
        render_markdown(summary),
        encoding="utf-8",
    )
    progress_path = args.report_dir / "batch_progress.json"
    if progress_path.exists():
        progress_path.unlink()
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {args.report_dir / 'batch_report.json'}", flush=True)
    print(f"Markdown report: {args.report_dir / 'batch_report.md'}", flush=True)


def ensure_batch_runtime_ready() -> None:
    readiness = asyncio.run(build_readiness_payload())
    failed_checks = {
        name: check
        for name, check in dict(readiness.get("checks") or {}).items()
        if str(check.get("status") or "").strip().lower() == "failed" and bool(check.get("blocking", True))
    }
    if not failed_checks:
        return
    detail = "; ".join(
        f"{name}={str(check.get('detail') or '').strip() or 'failed'}"
        for name, check in failed_checks.items()
    )
    raise SystemExit(f"Runtime readiness failed: {detail}")


def write_batch_progress(
    *,
    report_dir: Path,
    source_dir: Path,
    channel_profile: str,
    language: str,
    output_dir: str | None,
    enhancement_modes: list[str],
    reports: list[JobRunReport],
    current_item: dict[str, Any] | None = None,
    current_job_id: str | None = None,
    running_jobs: list[dict[str, Any]] | None = None,
    queued_items: list[dict[str, Any]] | None = None,
    status: str = "running",
) -> None:
    serialized_running_jobs = [
        {
            "job_id": str((entry or {}).get("job_id") or ""),
            "source_name": str(((entry or {}).get("item") or {}).get("source_name") or ""),
            "source_path": str(((entry or {}).get("item") or {}).get("path") or ""),
        }
        for entry in (running_jobs or [])
    ]
    serialized_queued_items = [
        {
            "source_name": str((entry or {}).get("source_name") or ""),
            "source_path": str((entry or {}).get("path") or ""),
        }
        for entry in (queued_items or [])
    ]
    current_payload = (
        serialized_running_jobs[0]
        if serialized_running_jobs
        else {
            "job_id": current_job_id or "",
            "source_name": str((current_item or {}).get("source_name") or ""),
            "source_path": str((current_item or {}).get("path") or ""),
        }
    )
    progress_payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source_dir": str(source_dir),
        "channel_profile": channel_profile,
        "language": language,
        "output_dir": output_dir,
        "enhancement_modes": list(enhancement_modes),
        "completed_job_count": len(reports),
        "running_job_count": len(serialized_running_jobs),
        "queued_job_count": len(serialized_queued_items),
        "jobs": [asdict(report) for report in reports],
        "current": current_payload,
        "running_jobs": serialized_running_jobs,
        "queued_jobs": serialized_queued_items,
    }
    (report_dir / "batch_progress.json").write_text(
        json.dumps(progress_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def select_source_candidates(source_dir: Path, limit: int, *, source_names: list[str] | None = None) -> list[dict[str, Any]]:
    candidates = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and "已剪" not in path.stem
    ]
    if source_names:
        by_name = {path.name: path for path in candidates}
        ordered = [by_name[name] for name in source_names if name in by_name]
        return [{"path": str(path), "source_name": path.name} for path in ordered[:limit]]
    candidates.sort(key=lambda path: (path.stat().st_size, path.name.lower()))
    return [{"path": str(path), "source_name": path.name} for path in candidates[:limit]]


async def prepare_job_for_source(
    source_path: Path,
    *,
    channel_profile: str,
    language: str,
    output_dir: str | None,
    enhancement_modes: list[str],
    force_rerun_existing: bool,
    fresh_jobs: bool = False,
) -> str | None:
    if not fresh_jobs:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Job).where(Job.source_name == source_path.name).order_by(Job.created_at.desc())
            )
            jobs = result.scalars().all()
            for job in jobs:
                render_result = await session.execute(
                    select(RenderOutput)
                    .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
                    .order_by(RenderOutput.created_at.desc())
                )
                render = render_result.scalars().first()
                if render and render.output_path and Path(render.output_path).exists() and not force_rerun_existing:
                    return None

            reusable = jobs[0] if jobs else None
            if reusable is not None:
                await reset_job_for_batch_rerun(
                    session,
                    reusable,
                    enhancement_modes=enhancement_modes,
                    output_dir=output_dir,
                )
                await session.commit()
                return str(reusable.id)
    else:
        job_id = await _create_job_for_file(
            source_path,
            workflow_template=channel_profile,
            language=language,
            output_dir=output_dir,
            allow_duplicate_file=True,
        )
        if not job_id:
            return None
        if enhancement_modes:
            await override_job_batch_settings(job_id, enhancement_modes=enhancement_modes, output_dir=output_dir)
        return job_id

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        workflow_template=channel_profile,
        language=language,
        output_dir=output_dir,
    )
    job_id = str(created[0].get("job_id") or "").strip() or None
    if not job_id:
        return None
    if enhancement_modes:
        await override_job_batch_settings(job_id, enhancement_modes=enhancement_modes, output_dir=output_dir)
    return job_id


async def reset_job_for_batch_rerun(
    session,
    job: Job,
    *,
    enhancement_modes: list[str],
    output_dir: str | None,
) -> None:
    await session.execute(delete(Artifact).where(Artifact.job_id == job.id))
    await session.execute(delete(RenderOutput).where(RenderOutput.job_id == job.id))
    await session.execute(delete(Timeline).where(Timeline.job_id == job.id))
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job.id))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job.id))

    step_result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
    existing_steps = {step.step_name: step for step in step_result.scalars().all()}
    now = datetime.now(timezone.utc)
    for step_name in PIPELINE_STEPS:
        step = existing_steps.get(step_name)
        preserved_metadata = {}
        if step is not None and step.step_name == "content_profile" and isinstance(step.metadata_, dict):
            source_context = step.metadata_.get("source_context")
            if isinstance(source_context, dict) and source_context:
                preserved_metadata["source_context"] = dict(source_context)
        if step is None:
            session.add(
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status="pending",
                    attempt=0,
                    metadata_=preserved_metadata or None,
                )
            )
            continue
        step.status = "pending"
        step.attempt = 0
        step.error_message = None
        step.started_at = None
        step.finished_at = None
        step.metadata_ = preserved_metadata or None

    if enhancement_modes:
        job.enhancement_modes = list(enhancement_modes)
    if output_dir:
        job.output_dir = output_dir
    job.status = "pending"
    job.error_message = None
    job.updated_at = now


async def override_job_batch_settings(job_id: str, *, enhancement_modes: list[str], output_dir: str | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if job is None:
            return
        if enhancement_modes:
            job.enhancement_modes = list(enhancement_modes)
        if output_dir:
            job.output_dir = output_dir
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()


def run_job(job_id: str, item: dict[str, Any], *, stop_after: str | None = None) -> JobRunReport:
    step_runs: list[StepRun] = []
    status = "done"
    current_steps = load_step_statuses(job_id)

    for step_name in PIPELINE_STEPS:
        if current_steps.get(step_name) == "done":
            if stop_after == step_name:
                status = "partial"
                break
            continue
        if step_name == "summary_review":
            started = time.perf_counter()
            auto_confirm_content_profile(job_id)
            current_steps["summary_review"] = "done"
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=read_step_detail(job_id, step_name),
                )
            )
            if stop_after == step_name:
                status = "partial"
                break
            continue
        mark_step(job_id, step_name, "running")
        started = time.perf_counter()
        step_timeout_seconds = _resolve_batch_step_timeout_seconds(step_name)
        try:
            _run_step_sync_with_timeout(step_name, job_id, step_timeout_seconds)
            observed_status = wait_for_step_completion_if_dispatched(
                job_id,
                step_name,
                timeout_seconds=step_timeout_seconds,
            )
            if observed_status != "done":
                mark_step(job_id, step_name, "done")
            current_steps[step_name] = "done"
            detail = read_step_detail(job_id, step_name)
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=detail,
                )
            )
            if stop_after == step_name:
                status = "partial"
                break
        except TimeoutError as exc:
            status = "failed"
            error_text = f"{type(exc).__name__}: {exc}"
            metadata_updates = getattr(exc, "__batch_step_execution_metadata__", None)
            mark_step(
                job_id,
                step_name,
                "failed",
                error=error_text,
                terminal_failure=True,
                metadata_updates=metadata_updates,
            )
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="failed",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=error_text,
                )
            )
            break
        except Exception as exc:
            status = "failed"
            error_text = f"{type(exc).__name__}: {exc}"
            failure_metadata = getattr(exc, "__batch_step_execution_metadata__", None)
            mark_step(
                job_id,
                step_name,
                "failed",
                error=error_text,
                terminal_failure=True,
                metadata_updates=failure_metadata,
            )
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="failed",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=error_text,
                )
            )
            break

    if status == "partial":
        stop_job_after_requested_step(job_id, stopped_after=stop_after or "")
    elif status in {"done", "failed"}:
        failure_error = next((item.error for item in reversed(step_runs) if item.error), None)
        finalize_job(job_id, status, error=failure_error)
    collected = asyncio.run(collect_job_report(job_id, item, step_runs, status, stop_after=stop_after))
    return collected


def wait_for_step_completion_if_dispatched(
    job_id: str,
    step_name: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 1.0,
) -> str | None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
    while True:
        status, metadata, error_message = read_step_status_payload(job_id, step_name)
        normalized_status = str(status or "").strip().lower()
        if normalized_status == "running" and _step_has_dispatched_task_metadata(metadata):
            if time.monotonic() >= deadline:
                exc = TimeoutError(f"步骤 {step_name} 已派发到 worker 但等待完成超过 {float(timeout_seconds):.1f} 秒")
                setattr(
                    exc,
                    "__batch_step_execution_metadata__",
                    {
                        "sync_runner_timeout_strategy": "worker_wait",
                        "sync_runner_timeout_seconds": float(timeout_seconds),
                        "sync_runner_step_name": str(step_name).strip().lower(),
                    },
                )
                raise exc
            time.sleep(max(0.1, float(poll_interval_seconds or 1.0)))
            continue
        if normalized_status == "done":
            return "done"
        if normalized_status in {"failed", "cancelled"}:
            detail = str((metadata or {}).get("detail") or error_message or "").strip()
            raise RuntimeError(f"步骤 {step_name} worker 执行失败: {detail or normalized_status}")
        return normalized_status or None


def _step_has_dispatched_task_metadata(metadata: dict[str, Any] | None) -> bool:
    payload = metadata if isinstance(metadata, dict) else {}
    return bool(
        str(payload.get("task_id") or payload.get("last_task_id") or "").strip()
        or str(payload.get("queue") or "").strip()
        or str(payload.get("dispatched_at") or "").strip()
    )


def load_step_statuses(job_id: str) -> dict[str, str]:
    async def _load() -> dict[str, str]:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(JobStep).where(JobStep.job_id == uuid.UUID(job_id)))
            return {step.step_name: step.status for step in result.scalars().all()}

    return asyncio.run(_load())


def read_step_status_payload(job_id: str, step_name: str) -> tuple[str, dict[str, Any], str]:
    async def _read() -> tuple[str, dict[str, Any], str]:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            if step is None:
                return "", {}, ""
            return (
                str(step.status or ""),
                dict(step.metadata_ or {}) if isinstance(step.metadata_, dict) else {},
                str(step.error_message or ""),
            )

    return asyncio.run(_read())


def _sync_runner_attempt_value(current_attempt: int | None, *, status: str, terminal_failure: bool) -> int:
    attempt = max(0, int(current_attempt or 0))
    normalized = str(status or "").strip().lower()
    if normalized == "running":
        return max(1, attempt)
    if normalized == "failed" and terminal_failure:
        return max(MAX_ATTEMPTS, attempt)
    return attempt


def mark_step(
    job_id: str,
    step_name: str,
    status: str,
    *,
    error: str | None = None,
    terminal_failure: bool = False,
    metadata_updates: dict[str, Any] | None = None,
) -> None:
    async def _update() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            if await session.get(Job, job_uuid) is None:
                raise RuntimeError(f"Job not found: {job_id}")
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
            )
            step = result.scalar_one()
            now = datetime.now(timezone.utc)
            metadata = dict(step.metadata_ or {})
            step.status = status
            step.attempt = _sync_runner_attempt_value(
                step.attempt,
                status=status,
                terminal_failure=terminal_failure,
            )
            if status == "running":
                step.started_at = now
                step.finished_at = None
                step.error_message = None
                metadata.pop("sync_runner_terminal_failure", None)
            elif status in {"done", "failed", "cancelled"}:
                step.finished_at = now
                step.error_message = error
                if status == "failed" and terminal_failure:
                    metadata["sync_runner_terminal_failure"] = True
                    metadata["detail"] = str(error or metadata.get("detail") or "").strip()
                elif status in {"done", "cancelled"}:
                    metadata.pop("sync_runner_terminal_failure", None)
                if isinstance(metadata_updates, dict):
                    metadata.update(metadata_updates)
            metadata["updated_at"] = now.isoformat()
            step.metadata_ = metadata
            await session.commit()

    asyncio.run(_update())


def read_step_detail(job_id: str, step_name: str) -> str:
    async def _read() -> str:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            metadata = (step.metadata_ or {}) if step else {}
            return str(metadata.get("detail") or "")

    return asyncio.run(_read())


def auto_confirm_content_profile(job_id: str) -> None:
    async def _confirm() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            job = await session.get(Job, job_uuid)
            draft_result = await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job.id, Artifact.artifact_type == "content_profile_draft")
                .order_by(Artifact.created_at.desc())
            )
            draft_artifact = draft_result.scalars().first()
            if draft_artifact is None:
                raise RuntimeError("content_profile_draft not found")

            final_profile = dict(draft_artifact.data_json or {})
            final_profile["review_mode"] = str(final_profile.get("review_mode") or "manual_confirmed")
            final_profile["user_feedback"] = {}

            review_result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
            )
            review_step = review_result.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if review_step is not None:
                review_step.status = "done"
                review_step.started_at = review_step.started_at or now
                review_step.finished_at = now
                review_step.error_message = None

            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=review_step.id if review_step else None,
                    artifact_type="content_profile_final",
                    data_json=final_profile,
                )
            )
            job.status = "processing"
            job.updated_at = now
            await session.commit()

    asyncio.run(_confirm())


def finalize_job(job_id: str, status: str, *, error: str | None = None) -> None:
    async def _finalize() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            now = datetime.now(timezone.utc)
            job.status = status
            job.updated_at = now
            if status == "done":
                job.error_message = None
            else:
                job.error_message = str(error or job.error_message or "Batch full-chain run failed").strip()
            await session.commit()

    asyncio.run(_finalize())


def stop_job_after_requested_step(job_id: str, *, stopped_after: str) -> None:
    async def _stop() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            job = await session.get(Job, job_uuid)
            if job is None:
                return
            result = await session.execute(select(JobStep).where(JobStep.job_id == job_uuid))
            steps = result.scalars().all()
            now = datetime.now(timezone.utc)
            detail = (
                f"批量回归在 {stopped_after} 后按 stop_after 主动停止，保留当前工件用于评估。"
                if stopped_after
                else "批量回归按 stop_after 主动停止，保留当前工件用于评估。"
            )
            for step in steps:
                metadata = dict(step.metadata_ or {})
                metadata["updated_at"] = now.isoformat()
                if step.status == "pending":
                    step.status = "skipped"
                    step.finished_at = now
                    metadata["detail"] = detail
                    step.metadata_ = metadata
                elif step.status == "running":
                    step.status = "cancelled"
                    step.error_message = "Stopped after requested step"
                    step.finished_at = now
                    metadata["detail"] = detail
                    step.metadata_ = metadata
            # Use a terminal job status so the orchestrator cannot continue the chain,
            # while the external batch report still records this run as `partial`.
            job.status = "cancelled"
            job.error_message = detail
            job.updated_at = now
            await session.commit()

    asyncio.run(_stop())


def _build_step_sync_runner_metadata(steps: list[JobStep]) -> dict[str, dict[str, Any]]:
    return {
        str(step.step_name): {
            str(key): value
            for key, value in dict(step.metadata_ or {}).items()
            if str(key).startswith("sync_runner_")
        }
        for step in steps
        if step.step_name and any(
            str(key).startswith("sync_runner_")
            for key in dict(step.metadata_ or {}).keys()
        )
    }


def _build_render_diagnostics(
    render_payload: dict[str, Any],
    steps: list[JobStep],
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    strategy_render_validation = (
        render_payload.get("strategy_render_validation")
        if isinstance(render_payload, dict)
        else None
    )
    if isinstance(strategy_render_validation, dict) and strategy_render_validation:
        diagnostics["strategy_render_validation"] = _normalize_strategy_render_validation_for_reporting(
            strategy_render_validation
        )
    avatar_result = render_payload.get("avatar_result") if isinstance(render_payload, dict) else None
    if isinstance(avatar_result, dict) and avatar_result:
        avatar_summary = _normalize_avatar_render_result_for_reporting(avatar_result)
        if avatar_summary:
            diagnostics["avatar_result"] = avatar_summary

    render_step = next((step for step in steps if str(step.step_name) == "render"), None)
    if render_step is not None:
        render_step_summary: dict[str, Any] = {}
        status = str(render_step.status or "").strip()
        if status:
            render_step_summary["status"] = status
        detail = ""
        metadata = render_step.metadata_ if isinstance(render_step.metadata_, dict) else {}
        if isinstance(metadata, dict):
            detail = str(metadata.get("detail") or "").strip()
        if detail:
            render_step_summary["detail"] = detail
        error = str(render_step.error_message or "").strip()
        if error:
            render_step_summary["error"] = error
        sync_runner = {
            str(key): value
            for key, value in metadata.items()
            if str(key).startswith("sync_runner_")
        }
        if sync_runner:
            render_step_summary["sync_runner"] = sync_runner
        if render_step_summary:
            diagnostics["render_step"] = _normalize_render_step_summary_for_reporting(render_step_summary)
    return diagnostics


def _merge_render_runtime_payloads(
    render_payload: dict[str, Any] | None,
    runtime_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(render_payload or {}) if isinstance(render_payload, dict) else {}
    runtime = runtime_payload if isinstance(runtime_payload, dict) else {}
    for key in ("avatar_result", "strategy_render_validation"):
        value = runtime.get(key)
        if isinstance(value, dict) and value:
            merged[key] = dict(value)
    return merged


def _normalize_strategy_render_validation_for_reporting(
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    source = validation if isinstance(validation, dict) else {}
    if not source:
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "schema",
        "check",
        "status",
        "reason",
        "strategy_type",
        "required",
        "blocking",
        "segment_count",
        "panel_count",
        "overlay_count",
        "unsafe_overlay_count",
        "accepted_cut_count",
        "high_risk_cut_count",
        "blocking_high_risk_cut_count",
        "boundary_energy_evidence_count",
        "boundary_frame_sample_count",
        "boundary_waveform_sample_count",
    ):
        value = source.get(key)
        if value not in (None, "", []):
            summary[key] = value
    blocking_reasons = [
        str(item).strip()
        for item in list(source.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    if blocking_reasons:
        summary["blocking_reasons"] = blocking_reasons
    checks = [dict(item) for item in list(source.get("checks") or []) if isinstance(item, dict)]
    if checks:
        summary["checks"] = checks
    review_gates = [str(item).strip() for item in list(source.get("review_gates") or []) if str(item).strip()]
    if review_gates:
        summary["review_gates"] = review_gates
    return summary


def _classify_avatar_runtime_reason_category(reason: str) -> str | None:
    return _shared_classify_avatar_runtime_reason_category(reason)


def _normalize_avatar_render_result_for_reporting(
    avatar_result: dict[str, Any] | None,
) -> dict[str, Any]:
    source = avatar_result if isinstance(avatar_result, dict) else {}
    if not source:
        return {}
    avatar_summary: dict[str, Any] = {}
    for key in ("status", "reason", "detail", "retryable", "profile_name"):
        value = source.get(key)
        if value not in (None, "", []):
            avatar_summary[key] = value
    reason = str(source.get("reason") or "").strip()
    reason_category = str(source.get("reason_category") or "").strip()
    if reason and not reason_category:
        reason_category = _classify_avatar_runtime_reason_category(reason) or ""
    if reason_category:
        avatar_summary["reason_category"] = reason_category
    error_metadata = source.get("error_metadata")
    if isinstance(error_metadata, dict) and error_metadata:
        avatar_summary["error_metadata"] = dict(error_metadata)
    return avatar_summary


def _normalize_cover_render_result_for_reporting(
    cover_result: dict[str, Any] | None,
) -> dict[str, Any]:
    source = cover_result if isinstance(cover_result, dict) else {}
    if not source:
        return {}
    cover_summary: dict[str, Any] = {}
    for key in ("status", "reason", "detail", "cover_path", "variant_count", "selection_review_recommended"):
        value = source.get(key)
        if value not in (None, "", []):
            cover_summary[key] = value
    return cover_summary


def _classify_render_failure_reason(
    *,
    error: str,
    detail: str = "",
    sync_runner: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    return _shared_classify_render_failure_reason(
        error=error,
        detail=detail,
        sync_runner=sync_runner,
    )


def _normalize_render_diagnostics_for_reporting(
    diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}
    strategy_render_validation = (
        dict(payload.get("strategy_render_validation") or {})
        if isinstance(payload.get("strategy_render_validation"), dict)
        else {}
    )
    if strategy_render_validation:
        payload["strategy_render_validation"] = _normalize_strategy_render_validation_for_reporting(
            strategy_render_validation
        )
    avatar_result = dict(payload.get("avatar_result") or {}) if isinstance(payload.get("avatar_result"), dict) else {}
    if avatar_result:
        payload["avatar_result"] = _normalize_avatar_render_result_for_reporting(avatar_result)

    render_step = dict(payload.get("render_step") or {}) if isinstance(payload.get("render_step"), dict) else {}
    if render_step:
        payload["render_step"] = _normalize_render_step_summary_for_reporting(render_step)
    return payload


def _normalize_render_step_summary_for_reporting(
    render_step: dict[str, Any] | None,
) -> dict[str, Any]:
    return _shared_normalize_render_step_summary_for_reporting(render_step)


async def collect_job_report(
    job_id: str,
    item: dict[str, Any],
    step_runs: list[StepRun],
    status: str,
    *,
    stop_after: str | None = None,
) -> JobRunReport:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        job = await session.get(Job, job_uuid)

        subtitle_result = await session.execute(
            select(SubtitleItem).where(SubtitleItem.job_id == job_uuid, SubtitleItem.version == 1)
        )
        subtitles = subtitle_result.scalars().all()

        transcript_result = await session.execute(
            select(TranscriptSegment).where(TranscriptSegment.job_id == job_uuid, TranscriptSegment.version == 1)
        )
        transcript_segments = transcript_result.scalars().all()

        correction_result = await session.execute(
            select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid)
        )
        corrections = correction_result.scalars().all()

        step_result = await session.execute(select(JobStep).where(JobStep.job_id == job_uuid))
        steps = step_result.scalars().all()

        render_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job_uuid, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_result.scalars().first()

        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        artifacts = artifact_result.scalars().all()
        render_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "render_outputs"), None)
        render_runtime_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == "render_runtime_diagnostics"),
            None,
        )
        packaging_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "platform_packaging_md"), None)
        subtitle_quality_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT),
            None,
        )
        subtitle_projection_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER),
            None,
        )
        subtitle_term_resolution_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH),
            None,
        )
        subtitle_consistency_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT),
            None,
        )
        transcript_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "transcript"), None)
        asr_quality_gate_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_ASR_QUALITY_GATE),
            None,
        )
        profile_artifact = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_type in {"content_profile_final", "content_profile", "content_profile_draft", "downstream_context"}
            ),
            None,
        )

        timeline_result = await session.execute(
            select(Timeline)
            .where(Timeline.job_id == job_uuid, Timeline.timeline_type == "editorial")
            .order_by(Timeline.created_at.desc(), Timeline.id.desc())
        )
        editorial_timeline = timeline_result.scalars().first()
        refine_decision_plan_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == "refine_decision_plan"),
            None,
        )

    refine_decision_plan = (
        refine_decision_plan_artifact.data_json
        if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
        else None
    )
    keep_ratio = compute_effective_keep_ratio(
        editorial_timeline.data_json if editorial_timeline else None,
        refine_decision_plan=refine_decision_plan,
        editorial_timeline_id=str(editorial_timeline.id) if editorial_timeline else "",
        editorial_timeline_version=int(editorial_timeline.version or 0) if editorial_timeline else 0,
    )
    output_path = str(render_output.output_path) if render_output and render_output.output_path else None
    output_duration = probe_duration(Path(output_path)) if output_path else 0.0
    render_payload = render_artifact.data_json if render_artifact and isinstance(render_artifact.data_json, dict) else {}
    render_runtime_payload = (
        render_runtime_artifact.data_json
        if render_runtime_artifact and isinstance(render_runtime_artifact.data_json, dict)
        else {}
    )
    render_payload = _merge_render_runtime_payloads(render_payload, render_runtime_payload)
    platform_doc = str(packaging_artifact.storage_path or "").strip() if packaging_artifact else None

    quality_assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=corrections,
        completion_candidate=(status == "done"),
    )
    step_sync_runner_metadata = _build_step_sync_runner_metadata(steps)
    render_diagnostics = _build_render_diagnostics(render_payload, steps)
    quality_assessment = _apply_terminal_status_to_quality_assessment(
        quality_assessment,
        status=status,
        render_diagnostics=render_diagnostics,
    )
    asr_evidence = _build_asr_evidence(
        transcript_artifact.data_json
        if transcript_artifact and isinstance(transcript_artifact.data_json, dict)
        else {},
        asr_quality_gate_artifact.data_json
        if asr_quality_gate_artifact and isinstance(asr_quality_gate_artifact.data_json, dict)
        else {},
    )
    subtitle_projection_data = (
        subtitle_projection_artifact.data_json
        if subtitle_projection_artifact and isinstance(subtitle_projection_artifact.data_json, dict)
        else {}
    )
    effective_subtitle_count = len(list(subtitle_projection_data.get("entries") or [])) or len(subtitles)
    report_content_profile = (
        strip_publication_only_profile_fields(profile_artifact.data_json)
        if profile_artifact and isinstance(profile_artifact.data_json, dict)
        else None
    )
    live_stage_validations = build_live_stage_validations(
        step_statuses={step.step_name: step.status for step in steps},
        step_details={
            str(step.step_name): str(((step.metadata_ or {}).get("detail") if isinstance(step.metadata_, dict) else "") or "")
            for step in steps
        },
        step_errors={
            str(step.step_name): str(step.error_message or "")
            for step in steps
        },
        step_metadata={
            str(step.step_name): dict(step.metadata_ or {})
            for step in steps
            if isinstance(step.metadata_, dict)
        },
        run_status=status,
        stop_after=stop_after,
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        keep_ratio=keep_ratio,
        profile=report_content_profile,
        platform_doc=platform_doc,
        subtitle_quality_report=subtitle_quality_artifact.data_json if subtitle_quality_artifact else None,
        subtitle_term_resolution_patch=(
            subtitle_term_resolution_artifact.data_json if subtitle_term_resolution_artifact else None
        ),
        subtitle_consistency_report=subtitle_consistency_artifact.data_json if subtitle_consistency_artifact else None,
        quality_assessment=quality_assessment,
    )

    notes = build_job_notes(
        status=status,
        output_duration=output_duration,
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        correction_count=len(corrections),
        keep_ratio=keep_ratio,
        quality_assessment=quality_assessment,
        live_stage_validations=live_stage_validations,
    )

    return JobRunReport(
        job_id=str(job_id),
        source_path=str(item.get("path") or ""),
        source_name=str(item.get("source_name") or job.source_name),
        status=status,
        output_path=output_path,
        cover_path=None,
        output_duration_sec=round(output_duration, 3),
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        correction_count=len(corrections),
        keep_ratio=round(keep_ratio, 3),
        cover_variant_count=0,
        platform_doc=None,
        quality_score=quality_assessment.get("score"),
        quality_grade=quality_assessment.get("grade"),
        quality_issue_codes=list(quality_assessment.get("issue_codes") or []),
        live_stage_validations=live_stage_validations,
        content_profile=report_content_profile,
        asr_evidence=asr_evidence,
        step_sync_runner_metadata=step_sync_runner_metadata,
        render_diagnostics=render_diagnostics,
        steps=step_runs,
        notes=notes,
    )


def _build_asr_evidence(
    transcript_payload: dict[str, Any],
    quality_gate_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(transcript_payload, dict):
        transcript_payload = {}
    if not isinstance(quality_gate_payload, dict):
        quality_gate_payload = {}
    if not transcript_payload and not quality_gate_payload:
        return {}
    source_payload = transcript_payload or quality_gate_payload
    attempts = [
        attempt
        for attempt in list(source_payload.get("attempts") or [])
        if isinstance(attempt, dict)
    ]
    rejected_attempts = [
        attempt
        for attempt in list(quality_gate_payload.get("rejected_attempts") or [])
        if isinstance(attempt, dict)
    ]
    if not attempts and rejected_attempts:
        for attempt in rejected_attempts:
            attempts.append(
                {
                    "provider": attempt.get("provider"),
                    "model": attempt.get("model"),
                    "error": quality_gate_payload.get("message") or "asr_quality_gate",
                }
            )
    summarized_attempts: list[dict[str, Any]] = []
    quality_gate_rejections: list[dict[str, Any]] = []
    for attempt in attempts:
        error = str(attempt.get("error") or "").strip()
        item = {
            "provider": str(attempt.get("provider") or "").strip(),
            "model": str(attempt.get("model") or "").strip(),
            "status": "rejected" if error else "selected",
        }
        if error:
            item["error"] = error
        summarized_attempts.append(item)
        if error.startswith("asr_quality_gate:") or (
            quality_gate_payload and "asr_quality_gate" in error
        ):
            quality_gate_rejections.append(item)

    provider = str(source_payload.get("provider") or "").strip()
    model = str(source_payload.get("model") or "").strip()
    if not provider and attempts:
        provider = str(attempts[-1].get("provider") or "").strip()
    if not model and attempts:
        model = str(attempts[-1].get("model") or "").strip()
    evidence = {
        "provider": provider,
        "model": model,
        "status": str(source_payload.get("status") or ("rejected" if quality_gate_payload else "selected")),
        "attempt_count": len(summarized_attempts),
        "fallback_used": (
            any(item.get("status") == "rejected" for item in summarized_attempts)
            and any(item.get("status") == "selected" for item in summarized_attempts)
        ),
        "attempts": summarized_attempts,
        "quality_gate_rejections": quality_gate_rejections,
    }
    if quality_gate_payload.get("message"):
        evidence["error"] = quality_gate_payload.get("message")
    if source_payload.get("language"):
        evidence["language"] = source_payload.get("language")
    if source_payload.get("duration"):
        evidence["duration_sec"] = source_payload.get("duration")
    return evidence


def compute_keep_ratio(editorial_timeline: dict[str, Any] | None) -> float:
    segments = list((editorial_timeline or {}).get("segments") or [])
    if not segments:
        return 0.0
    kept = 0.0
    total = 0.0
    for segment in segments:
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", 0.0) or 0.0)
        duration = max(0.0, end - start)
        total += duration
        if segment.get("type") == "keep":
            kept += duration
    return (kept / total) if total > 0 else 0.0


def compute_effective_keep_ratio(
    editorial_timeline: dict[str, Any] | None,
    *,
    refine_decision_plan: dict[str, Any] | None = None,
    editorial_timeline_id: str = "",
    editorial_timeline_version: int = 0,
) -> float:
    fallback_ratio = compute_keep_ratio(editorial_timeline)
    if not isinstance(editorial_timeline, dict):
        return fallback_ratio
    timeline_segments = [dict(item) for item in list(editorial_timeline.get("segments") or []) if isinstance(item, dict)]
    if not timeline_segments:
        return fallback_ratio
    total = 0.0
    for segment in timeline_segments:
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", 0.0) or 0.0)
        total += max(0.0, end - start)
    if total <= 0:
        return fallback_ratio
    resolved_keep_segments = resolve_refine_keep_segments_for_timeline(
        refine_decision_plan,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
        fallback_segments=timeline_segments,
    )
    if not resolved_keep_segments:
        return fallback_ratio
    kept = 0.0
    for segment in resolved_keep_segments:
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        kept += max(0.0, end - start)
    return (kept / total) if total > 0 else fallback_ratio


def classify_step_issue_codes(step_name: str, *, error: str, detail: str = "") -> list[str]:
    normalized_error = str(error or "").strip().lower()
    normalized_detail = str(detail or "").strip().lower()
    haystack = f"{normalized_error}\n{normalized_detail}".strip()
    if not haystack:
        return []
    if step_name == "probe":
        if "filenotfounderror" in haystack or "no such file" in haystack:
            return ["source_file_missing"]
        if "missing video stream" in haystack or "no usable video stream" in haystack:
            return ["missing_video_stream"]
        if "ffprobe failed" in haystack:
            return ["media_probe_failed"]
        return ["probe_failed"]
    if step_name == "extract_audio":
        if "filenotfounderror" in haystack or "no such file" in haystack:
            return ["source_file_missing"]
        if "noaudiostreamerror" in haystack or "无音轨" in haystack:
            return ["missing_audio_stream"]
        return ["extract_audio_failed"]
    return [f"{step_name}_failed"]


def build_live_stage_validations(
    *,
    step_statuses: dict[str, str],
    step_details: dict[str, str] | None,
    step_errors: dict[str, str] | None,
    step_metadata: dict[str, dict[str, Any]] | None,
    run_status: str,
    stop_after: str | None,
    transcript_segment_count: int,
    subtitle_count: int,
    keep_ratio: float,
    profile: dict[str, Any] | None,
    platform_doc: str | None,
    subtitle_quality_report: dict[str, Any] | None,
    subtitle_term_resolution_patch: dict[str, Any] | None,
    subtitle_consistency_report: dict[str, Any] | None,
    quality_assessment: dict[str, Any] | None,
) -> list[LiveStageValidation]:
    issue_codes = {str(code) for code in (quality_assessment or {}).get("issue_codes") or []}
    subtitle_quality_report = subtitle_quality_report if isinstance(subtitle_quality_report, dict) else {}
    subtitle_term_resolution_patch = (
        subtitle_term_resolution_patch if isinstance(subtitle_term_resolution_patch, dict) else {}
    )
    subtitle_consistency_report = subtitle_consistency_report if isinstance(subtitle_consistency_report, dict) else {}
    profile_issue_codes = [
        code
        for code in (
            "missing_content_profile",
            "low_profile_confidence",
            "profile_unconfirmed",
            "generic_subject_type",
            "generic_video_theme",
            "generic_summary",
            "thin_summary",
            "detail_blind",
            "detail_coverage_low",
            "comparison_blind",
        )
        if code in issue_codes
    ]
    profile_review_mode = str((profile or {}).get("review_mode") or "").strip().lower()
    profile_confirmed = bool((profile or {}).get("manual_confirmed")) or profile_review_mode in {
        "manual_confirmed",
        "auto_confirmed",
    }
    content_profile_passed = bool(profile) and not profile_issue_codes and (
        step_statuses.get("content_profile") == "done"
        or step_statuses.get("summary_review") == "done"
        or profile_confirmed
    )
    subtitle_quality_blocking = bool(subtitle_quality_report.get("blocking"))
    subtitle_quality_warnings = list(subtitle_quality_report.get("warning_reasons") or [])
    pending_term_count = int((subtitle_term_resolution_patch.get("metrics") or {}).get("pending_count") or 0)
    subtitle_consistency_blocking = bool(subtitle_consistency_report.get("blocking"))
    subtitle_consistency_warnings = list(subtitle_consistency_report.get("warning_reasons") or [])
    has_term_resolution_step = "subtitle_term_resolution" in step_statuses
    has_consistency_step = "subtitle_consistency_review" in step_statuses
    has_summary_review_step = "summary_review" in step_statuses
    stage_to_step = {
        "probe": "probe",
        "transcribe": "transcribe",
        "subtitle_postprocess": "subtitle_postprocess",
        "subtitle_term_resolution": "subtitle_term_resolution",
        "subtitle_consistency_review": "subtitle_consistency_review",
        "content_profile": "content_profile",
        "summary_review": "summary_review",
        "edit_plan": "edit_plan",
        "render": "render",
    }
    pipeline_step_order = {step_name: index for index, step_name in enumerate(PIPELINE_STEPS)}
    stop_after_index = pipeline_step_order.get(str(stop_after or "").strip())
    first_failed_step_name = next(
        (
            step_name
            for step_name in PIPELINE_STEPS
            if step_statuses.get(step_name) == "failed"
        ),
        None,
    )
    first_failed_step_index = pipeline_step_order.get(first_failed_step_name) if first_failed_step_name else None
    step_details = {str(key): str(value or "") for key, value in dict(step_details or {}).items()}
    step_errors = {str(key): str(value or "") for key, value in dict(step_errors or {}).items()}
    step_metadata = {
        str(key): dict(value or {})
        for key, value in dict(step_metadata or {}).items()
        if isinstance(value, dict)
    }
    probe_detail = step_details.get("probe", "")
    probe_error = step_errors.get("probe", "")
    transcribe_detail = step_details.get("transcribe", "")
    subtitle_postprocess_detail = step_details.get("subtitle_postprocess", "")
    edit_plan_metadata = dict(step_metadata.get("edit_plan") or {})
    edit_plan_audio_rebuilt = bool(edit_plan_metadata.get("audio_artifact_rebuilt"))
    no_audio_transcribe = "无音轨" in transcribe_detail and "跳过转写" in transcribe_detail
    no_audio_subtitle_postprocess = "0 段 -> 0 条" in subtitle_postprocess_detail and no_audio_transcribe
    empty_transcribe_completed = step_statuses.get("transcribe") == "done" and transcript_segment_count <= 0 and "共 0 段" in transcribe_detail
    empty_subtitle_postprocess_completed = (
        step_statuses.get("subtitle_postprocess") == "done"
        and subtitle_count <= 0
        and "0 段 -> 0 条" in subtitle_postprocess_detail
    )
    render_detail = step_details.get("render", "")
    render_error = step_errors.get("render", "")
    render_metadata = dict(step_metadata.get("render") or {})
    render_failure_reason, render_failure_issue_codes = _classify_render_failure_reason(
        error=render_error,
        detail=render_detail,
        sync_runner=render_metadata,
    )
    render_done = step_statuses.get("render") == "done"
    render_issue_codes = (
        ["subtitle_sync_issue"]
        if "subtitle_sync_issue" in issue_codes
        else list(render_failure_issue_codes or ["render_failed"])
        if not render_done
        else []
    )
    render_summary = (
        "导出成片字幕同步正常"
        if render_done and "subtitle_sync_issue" not in issue_codes
        else "导出层存在字幕同步/结构问题"
        if "subtitle_sync_issue" in issue_codes
        else f"导出成片失败：{render_failure_reason or 'render_failed'}"
    )

    def _stage_skipped(stage: str) -> bool:
        if str(run_status or "").strip().lower() != "partial" or stop_after_index is None:
            return False
        mapped_step = stage_to_step.get(stage)
        if not mapped_step:
            return False
        mapped_index = pipeline_step_order.get(mapped_step)
        if mapped_index is None:
            return False
        return mapped_index > stop_after_index

    def _skipped_validation(stage: str) -> LiveStageValidation:
        return LiveStageValidation(
            stage=stage,
            status="skipped",
            summary=f"{stage} 因 stop_after 未执行",
            issue_codes=[],
        )

    def _blocked_validation(stage: str) -> LiveStageValidation | None:
        mapped_step = stage_to_step.get(stage)
        mapped_index = pipeline_step_order.get(mapped_step) if mapped_step else None
        if (
            first_failed_step_name is None
            or first_failed_step_index is None
            or mapped_index is None
            or mapped_index <= first_failed_step_index
            or step_statuses.get(mapped_step) not in {"pending", "skipped", "cancelled"}
        ):
            return None
        return LiveStageValidation(
            stage=stage,
            status="skipped",
            summary=f"{stage} 因上游 {first_failed_step_name} 失败未执行",
            issue_codes=[],
        )

    validations = [
        LiveStageValidation(
            stage="probe",
            status=(
                "pass"
                if step_statuses.get("probe") == "done"
                else "warn"
                if step_statuses.get("probe") in {"skipped", "cancelled"}
                else "fail"
            ),
            summary=(
                probe_error
                or probe_detail
                or "媒体探测完成"
                if step_statuses.get("probe") == "done"
                else probe_error
                or probe_detail
                or "媒体探测失败"
            ),
            issue_codes=(
                classify_step_issue_codes("probe", error=probe_error, detail=probe_detail)
                if step_statuses.get("probe") == "failed"
                else []
            ),
        ),
        _blocked_validation("transcribe") or LiveStageValidation(
            stage="transcribe",
            status=(
                "pass"
                if step_statuses.get("transcribe") == "done" and (transcript_segment_count > 0 or no_audio_transcribe)
                else "warn"
                if empty_transcribe_completed
                else "fail"
            ),
            summary=(
                transcribe_detail
                if no_audio_transcribe and transcribe_detail
                else transcribe_detail
                if empty_transcribe_completed and transcribe_detail
                else f"ASR 产出 {transcript_segment_count} 条 transcript segment"
            ),
            issue_codes=(
                []
                if (transcript_segment_count > 0 or no_audio_transcribe)
                else ["empty_transcript_completed"]
                if empty_transcribe_completed
                else ["missing_transcript"]
            ),
        ),
        _skipped_validation("subtitle_postprocess") if _stage_skipped("subtitle_postprocess") else _blocked_validation("subtitle_postprocess") or LiveStageValidation(
            stage="subtitle_postprocess",
            status=(
                "fail"
                if step_statuses.get("subtitle_postprocess") != "done"
                or subtitle_quality_blocking
                else "pass"
                if no_audio_subtitle_postprocess
                else "warn"
                if empty_subtitle_postprocess_completed
                else "warn"
                if subtitle_quality_warnings
                else "fail"
                if subtitle_count <= 0
                else "pass"
            ),
            summary=(
                subtitle_postprocess_detail
                if no_audio_subtitle_postprocess and subtitle_postprocess_detail
                else subtitle_postprocess_detail
                if empty_subtitle_postprocess_completed and subtitle_postprocess_detail
                else
                f"字幕后处理产出 {subtitle_count} 条字幕，基础质检阻断 {len(subtitle_quality_report.get('blocking_reasons') or [])} 项"
                if subtitle_quality_blocking
                else f"字幕后处理产出 {subtitle_count} 条字幕"
            ),
            issue_codes=(
                list(subtitle_quality_report.get("blocking_reasons") or [])
                if subtitle_quality_blocking
                else ["empty_subtitles_completed"]
                if empty_subtitle_postprocess_completed
                else ["missing_subtitles"]
                if subtitle_count <= 0 and not no_audio_subtitle_postprocess
                else list(subtitle_quality_warnings)
            ),
        ),
        _skipped_validation("subtitle_term_resolution") if _stage_skipped("subtitle_term_resolution") else _blocked_validation("subtitle_term_resolution") or LiveStageValidation(
            stage="subtitle_term_resolution",
            status=(
                "fail"
                if pending_term_count > 0
                or (has_term_resolution_step and step_statuses.get("subtitle_term_resolution") != "done")
                else "pass"
            ),
            summary=(
                f"术语候选 {int((subtitle_term_resolution_patch.get('metrics') or {}).get('patch_count') or 0)} 条，待确认 {pending_term_count} 条"
                if pending_term_count > 0 or subtitle_term_resolution_patch
                else "术语解析未启用或无待确认项"
            ),
            issue_codes=["subtitle_terms_pending"] if pending_term_count > 0 else [],
        ),
        _skipped_validation("subtitle_consistency_review") if _stage_skipped("subtitle_consistency_review") else _blocked_validation("subtitle_consistency_review") or LiveStageValidation(
            stage="subtitle_consistency_review",
            status=(
                "fail"
                if subtitle_consistency_blocking
                or (has_consistency_step and step_statuses.get("subtitle_consistency_review") != "done")
                else "warn"
                if subtitle_consistency_warnings
                else "pass"
            ),
            summary=(
                "字幕一致性存在阻断项"
                if subtitle_consistency_blocking
                else "字幕一致性存在提醒项"
                if subtitle_consistency_warnings
                else "字幕一致性审校通过"
                if has_consistency_step
                else "字幕一致性审校未启用"
            ),
            issue_codes=(
                list(subtitle_consistency_report.get("blocking_reasons") or [])
                if subtitle_consistency_blocking
                else list(subtitle_consistency_warnings)
            ),
        ),
        _skipped_validation("content_profile") if _stage_skipped("content_profile") else _blocked_validation("content_profile") or LiveStageValidation(
            stage="content_profile",
            status="pass" if content_profile_passed else "fail",
            summary="内容画像已通过 live 质量门禁" if content_profile_passed else "内容画像存在质量问题",
            issue_codes=profile_issue_codes,
        ),
        _skipped_validation("summary_review") if _stage_skipped("summary_review") else _blocked_validation("summary_review") or LiveStageValidation(
            stage="summary_review",
            status="pass" if not has_summary_review_step or step_statuses.get("summary_review") == "done" else "fail",
            summary=(
                "内容画像已确认冻结"
                if step_statuses.get("summary_review") == "done"
                else "内容画像无需人工确认"
                if not has_summary_review_step
                else "内容画像仍待确认"
            ),
            issue_codes=[] if not has_summary_review_step or step_statuses.get("summary_review") == "done" else ["summary_review_pending"],
        ),
        _skipped_validation("edit_plan") if _stage_skipped("edit_plan") else _blocked_validation("edit_plan") or LiveStageValidation(
            stage="edit_plan",
            status=(
                "fail"
                if not (step_statuses.get("edit_plan") == "done" and keep_ratio > 0)
                else "pass"
            ),
            summary=(
                "剪辑保留段为空或未生成"
                if keep_ratio <= 0
                else f"剪辑保留比 {keep_ratio:.0%}；音频派生文件缺失，已从源视频重建"
                if edit_plan_audio_rebuilt
                else f"剪辑保留比 {keep_ratio:.0%}"
            ),
            issue_codes=["empty_edit_plan"] if keep_ratio <= 0 else ["audio_artifact_rebuilt"] if edit_plan_audio_rebuilt else [],
        ),
        _skipped_validation("render") if _stage_skipped("render") else _blocked_validation("render") or LiveStageValidation(
            stage="render",
            status="pass" if render_done and "subtitle_sync_issue" not in issue_codes else "fail",
            summary=render_summary,
            issue_codes=render_issue_codes,
        ),
    ]
    return validations


def build_job_notes(
    *,
    status: str,
    output_duration: float,
    transcript_segment_count: int,
    subtitle_count: int,
    correction_count: int,
    keep_ratio: float,
    quality_assessment: dict[str, Any] | None,
    live_stage_validations: list[LiveStageValidation],
) -> list[str]:
    notes: list[str] = []
    if status == "done":
        notes.append("全链路跑通")
    elif status == "partial":
        notes.append("执行到指定阶段后停止")
    else:
        notes.append("任务未完整跑通")
    if output_duration > 0:
        notes.append(f"成片时长 {output_duration:.1f}s")
    if transcript_segment_count > 0:
        notes.append(f"ASR片段 {transcript_segment_count} 条")
    if subtitle_count > 0:
        notes.append(f"字幕 {subtitle_count} 条")
    if correction_count > 0:
        notes.append(f"术语/字幕纠正 {correction_count} 处")
    if keep_ratio > 0:
        notes.append(f"保留比 {keep_ratio:.0%}")
    if isinstance(quality_assessment, dict):
        grade = str(quality_assessment.get("grade") or "").strip()
        score = quality_assessment.get("score")
        if grade and score is not None:
            notes.append(f"质量分 {grade} {float(score):.1f}")
    failing_stages = [item.stage for item in live_stage_validations if item.status == "fail"]
    warning_stages = [item.stage for item in live_stage_validations if item.status == "warn"]
    if failing_stages:
        notes.append("live校验失败: " + "、".join(failing_stages[:4]))
    elif warning_stages:
        notes.append("live校验告警: " + "、".join(warning_stages[:4]))
    elif live_stage_validations:
        notes.append("live校验通过")
    return notes


def probe_duration(path: Path) -> float:
    import subprocess

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        data = json.loads(result.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    jobs = summary["jobs"]
    payload = {
        "job_count": summary["job_count"],
        "success_count": summary["success_count"],
        "failed_count": summary["failed_count"],
        "jobs": [
            {
                "source_name": job["source_name"],
                "status": job["status"],
                "output_duration_sec": job["output_duration_sec"],
                "quality_score": job.get("quality_score"),
                "quality_grade": job.get("quality_grade"),
                "asr_evidence": {
                    "status": (job.get("asr_evidence") or {}).get("status"),
                    "provider": (job.get("asr_evidence") or {}).get("provider"),
                    "model": (job.get("asr_evidence") or {}).get("model"),
                    "fallback_used": (job.get("asr_evidence") or {}).get("fallback_used"),
                    "attempt_count": (job.get("asr_evidence") or {}).get("attempt_count"),
                    "error": (job.get("asr_evidence") or {}).get("error"),
                },
                "subtitle_count": job["subtitle_count"],
                "keep_ratio": job["keep_ratio"],
                "notes": job["notes"][:4],
            }
            for job in jobs
        ],
    }
    if isinstance(summary.get("live_readiness"), dict):
        payload["live_readiness"] = {
            "status": summary["live_readiness"].get("status"),
            "gate_passed": summary["live_readiness"].get("gate_passed"),
            "summary": summary["live_readiness"].get("summary"),
            "stable_run_count": summary["live_readiness"].get("stable_run_count"),
        }
    return payload


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Full-Chain Batch Report",
        "",
        f"- created_at: {summary['created_at']}",
        f"- source_dir: {summary['source_dir']}",
        f"- channel_profile: {summary['channel_profile']}",
        f"- language: {summary['language']}",
        f"- output_dir: {summary.get('output_dir') or ''}",
        f"- enhancement_modes: {', '.join(summary.get('enhancement_modes') or [])}",
        f"- success_count: {summary['success_count']}/{summary['job_count']}",
        "",
    ]
    live_readiness = summary.get("live_readiness") if isinstance(summary.get("live_readiness"), dict) else {}
    if live_readiness:
        lines.extend(
            [
                "## Live Readiness",
                "",
                f"- status: {live_readiness.get('status')}",
                f"- gate_passed: {str(bool(live_readiness.get('gate_passed'))).lower()}",
                f"- summary: {live_readiness.get('summary') or ''}",
                f"- stable_run_count: {live_readiness.get('stable_run_count')}/{live_readiness.get('required_stable_runs')}",
                f"- golden_job_count: {live_readiness.get('golden_job_count')}",
                f"- evaluated_job_count: {live_readiness.get('evaluated_job_count')}",
            ]
        )
        checks = live_readiness.get("checks") if isinstance(live_readiness.get("checks"), dict) else {}
        if checks:
            lines.append("- checks:")
            for key, value in checks.items():
                if isinstance(value, dict):
                    lines.append(
                        f"  - {key}: pass={str(bool(value.get('passed'))).lower()} "
                        f"actual={value.get('actual')} required={value.get('required')}"
                    )
        if live_readiness.get("failure_reasons"):
            lines.append("- failure_reasons: " + " / ".join(live_readiness["failure_reasons"]))
        if live_readiness.get("warning_reasons"):
            lines.append("- warning_reasons: " + " / ".join(live_readiness["warning_reasons"]))
        lines.append("")
    for job in summary["jobs"]:
        lines.append(f"## {job['source_name']}")
        lines.append(f"- status: {job['status']}")
        lines.append(f"- output_path: {job['output_path'] or ''}")
        lines.append(f"- output_duration_sec: {job['output_duration_sec']}")
        lines.append(f"- transcript_segment_count: {job.get('transcript_segment_count', 0)}")
        lines.append(f"- subtitle_count: {job['subtitle_count']}")
        lines.append(f"- correction_count: {job['correction_count']}")
        lines.append(f"- keep_ratio: {job['keep_ratio']}")
        if job.get("quality_score") is not None:
            lines.append(f"- quality: {job.get('quality_grade') or ''} {job['quality_score']}")
        if job.get("quality_issue_codes"):
            lines.append("- quality_issue_codes: " + ", ".join(job["quality_issue_codes"]))
        asr_evidence = job.get("asr_evidence") if isinstance(job.get("asr_evidence"), dict) else {}
        if asr_evidence:
            lines.append(
                "- asr_evidence: "
                + ", ".join(
                    [
                        f"provider={asr_evidence.get('provider') or ''}",
                        f"model={asr_evidence.get('model') or ''}",
                        f"attempt_count={asr_evidence.get('attempt_count') or 0}",
                        f"fallback_used={str(bool(asr_evidence.get('fallback_used'))).lower()}",
                    ]
                )
            )
            attempts = list(asr_evidence.get("attempts") or [])
            if attempts:
                lines.append("  - asr_attempts:")
                for attempt in attempts:
                    if not isinstance(attempt, dict):
                        continue
                    attempt_line = (
                        f"    - {attempt.get('provider') or ''}/{attempt.get('model') or ''}: "
                        f"{attempt.get('status') or ''}"
                    )
                    if attempt.get("error"):
                        attempt_line += f" | error={attempt['error']}"
                    lines.append(attempt_line)
        if job.get("live_stage_validations"):
            lines.append(
                "- live_stage_validations: "
                + " / ".join(
                    f"{item['stage']}={item['status']}"
                    for item in job["live_stage_validations"]
                )
            )
            for item in job["live_stage_validations"]:
                detail = f"  - {item['stage']}: {item['status']} | {item['summary']}"
                issue_codes = list(item.get("issue_codes") or [])
                if issue_codes:
                    detail += " | issues=" + ", ".join(issue_codes)
                lines.append(detail)
        if job.get("content_profile"):
            profile = job["content_profile"]
            lines.append(
                "- content_profile: "
                + " | ".join(
                    filter(
                        None,
                        [
                            str(profile.get("subject_brand") or "").strip(),
                            str(profile.get("subject_model") or "").strip(),
                            str(profile.get("subject_type") or "").strip(),
                            str(profile.get("video_theme") or "").strip(),
                        ],
                    )
                )
            )
        render_diagnostics = job.get("render_diagnostics") if isinstance(job.get("render_diagnostics"), dict) else {}
        if render_diagnostics:
            avatar_result = (
                render_diagnostics.get("avatar_result")
                if isinstance(render_diagnostics.get("avatar_result"), dict)
                else {}
            )
            render_step = (
                render_diagnostics.get("render_step")
                if isinstance(render_diagnostics.get("render_step"), dict)
                else {}
            )
            if avatar_result:
                avatar_parts = [
                    f"{key}={avatar_result[key]}"
                    for key in ("status", "reason", "reason_category", "retryable", "profile_name")
                    if key in avatar_result
                ]
                if avatar_result.get("detail"):
                    avatar_parts.append(f"detail={avatar_result['detail']}")
                if avatar_result.get("error_metadata"):
                    avatar_parts.append(
                        "error_metadata=" + json.dumps(avatar_result["error_metadata"], ensure_ascii=False, sort_keys=True)
                    )
                lines.append("- render_avatar: " + ", ".join(avatar_parts))
            strategy_render_validation = (
                render_diagnostics.get("strategy_render_validation")
                if isinstance(render_diagnostics.get("strategy_render_validation"), dict)
                else {}
            )
            if strategy_render_validation:
                strategy_parts = [
                    f"{key}={strategy_render_validation[key]}"
                    for key in (
                        "status",
                        "reason",
                        "strategy_type",
                        "required",
                        "blocking",
                        "segment_count",
                        "panel_count",
                        "overlay_count",
                        "unsafe_overlay_count",
                        "accepted_cut_count",
                        "high_risk_cut_count",
                        "blocking_high_risk_cut_count",
                        "boundary_energy_evidence_count",
                        "boundary_frame_sample_count",
                        "boundary_waveform_sample_count",
                    )
                    if key in strategy_render_validation
                ]
                if strategy_render_validation.get("blocking_reasons"):
                    strategy_parts.append(
                        "blocking_reasons=" + ",".join(strategy_render_validation["blocking_reasons"])
                    )
                if strategy_render_validation.get("review_gates"):
                    strategy_parts.append("review_gates=" + ",".join(strategy_render_validation["review_gates"]))
                lines.append("- render_strategy_validation: " + ", ".join(strategy_parts))
            if render_step:
                render_step_parts = [
                    f"{key}={render_step[key]}"
                    for key in ("status", "reason", "detail", "error")
                    if key in render_step
                ]
                if render_step.get("issue_codes"):
                    render_step_parts.append("issue_codes=" + ",".join(render_step["issue_codes"]))
                if render_step.get("sync_runner"):
                    render_step_parts.append(
                        "sync_runner="
                        + json.dumps(render_step["sync_runner"], ensure_ascii=False, sort_keys=True)
                    )
                lines.append("- render_step: " + ", ".join(render_step_parts))
        if job.get("steps"):
            step_sync_metadata = {
                str(step_name): metadata
                for step_name, metadata in dict(
                    job.get("step_sync_runner_metadata") or {}
                ).items()
            }
            lines.append("- steps:")
            for item in job["steps"]:
                step_line = f"  - {item['step']}: {item['status']} ({item['elapsed_seconds']}s)"
                if item.get("detail"):
                    step_line += f" | {item['detail']}"
                if item.get("error"):
                    step_line += f" | error={item['error']}"
                sync_metadata = step_sync_metadata.get(str(item["step"]) if isinstance(item, dict) else "")
                if sync_metadata:
                    sync_metadata_text = ", ".join(
                        f"{key}={sync_metadata[key]}" for key in sorted(sync_metadata)
                    )
                    step_line += f" | sync_runner={{{sync_metadata_text}}}"
                lines.append(step_line)
        if job.get("notes"):
            lines.append("- notes: " + " / ".join(job["notes"]))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def resolve_golden_source_names(*, source_names: list[str] | None, golden_manifest: Path | None) -> list[str]:
    manifest_names = load_golden_manifest(golden_manifest) if golden_manifest else []
    explicit_names = [str(item).strip() for item in list(source_names or []) if str(item).strip()]
    ordered: list[str] = []
    for name in [*explicit_names, *manifest_names]:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def resolve_target_source_names(
    *,
    explicit_source_names: list[str] | None,
    source_manifest: Path | None,
    pollution_audit: Path | None,
    manual_review_only: bool,
) -> list[str]:
    ordered: list[str] = []

    def _append(names: list[str]) -> None:
        for name in names:
            normalized = str(name or "").strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)

    _append([str(item).strip() for item in list(explicit_source_names or []) if str(item).strip()])
    _append(load_golden_manifest(source_manifest) if source_manifest else [])
    _append(load_source_names_from_pollution_audit(pollution_audit, manual_review_only=manual_review_only))
    return ordered


def load_source_names_from_pollution_audit(
    path: Path | None,
    *,
    manual_review_only: bool,
) -> list[str]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []

    names: list[str] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if manual_review_only and not bool(item.get("manual_review_required")):
            continue
        source_name = str(item.get("source_name") or "").strip()
        if source_name and source_name not in names:
            names.append(source_name)
    return names


def load_golden_manifest(path: Path | None) -> list[str]:
    if path is None:
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("golden manifest JSON must be an array of source names")
        return [str(item).strip() for item in data if str(item).strip()]
    return [line.strip() for line in raw.splitlines() if line.strip()]


def load_previous_batch_summaries(paths: list[str] | list[Path]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for raw_path in list(paths or []):
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            summaries.append(payload)
    return summaries


if __name__ == "__main__":
    main()
