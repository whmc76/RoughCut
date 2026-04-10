from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ["TELEGRAM_REMOTE_REVIEW_ENABLED"] = "false"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.pipeline.steps import run_step_sync
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths, suggest_merge_groups_for_inventory_items

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
PROFILE_STEPS = ["content_profile", "glossary_review"]
FULL_CHAIN_STEPS = ["probe", "extract_audio", "transcribe", "subtitle_postprocess", *PROFILE_STEPS]


@dataclass
class RowReport:
    source_name: str
    status: str
    job_id: str | None
    rerun_mode: str | None
    summary: str | None
    subject_brand: str | None
    subject_model: str | None
    subject_type: str | None
    video_theme: str | None
    subtitle_correction_count: int | None
    pending_correction_count: int | None
    needs_review: bool | None
    review_reasons: list[str]
    verification_conflict_count: int | None
    verification_missing_supported_fields: list[str]
    note: str | None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a repeatable EDC summary/proofreading regression on a source folder."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(r"Y:\EDC系列\未剪辑视频"),
    )
    parser.add_argument("--workflow-template", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "output" / "test",
    )
    parser.add_argument(
        "--report-prefix",
        default="edc_summary_regression",
    )
    parser.add_argument(
        "--baseline-json",
        type=Path,
        default=ROOT / "output" / "test" / "edc_summary_current_report.json",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--samples", nargs="*", default=[])
    return parser.parse_args()


def list_source_files(source_dir: Path, limit: int = 0, samples: list[str] | None = None) -> list[Path]:
    sample_names = {str(item).strip() for item in (samples or []) if str(item).strip()}
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        and (not sample_names or path.name in sample_names)
    ]
    files.sort(key=lambda path: (str(path.parent).lower(), path.name.lower()))
    if limit > 0:
        return files[:limit]
    return files


async def clone_or_prepare_job_for_source(
    source_path: Path,
    *,
    workflow_template: str,
    language: str,
) -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job).where(Job.source_name == source_path.name).order_by(Job.created_at.desc(), Job.id.desc())
        )
        source_jobs = list(result.scalars().all())
        if source_jobs:
            cloned_job_id, rerun_mode = await _clone_evaluation_job_from_existing(
                session,
                source_job=source_jobs[0],
                workflow_template=workflow_template,
                language=language,
            )
            await session.commit()
            return str(cloned_job_id), rerun_mode

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        workflow_template=workflow_template,
        language=language,
    )
    job_id = str(created[0].get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"Failed to create job for {source_path.name}")
    return job_id, "fresh_full_chain"


async def _clone_evaluation_job_from_existing(
    session,
    *,
    source_job: Job,
    workflow_template: str,
    language: str,
) -> tuple[uuid.UUID, str]:
    transcript_rows = (
        await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == source_job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
    ).scalars().all()
    subtitle_rows = (
        await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == source_job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
    ).scalars().all()
    media_meta_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "media_meta")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()
    audio_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "audio_wav")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()

    job_id = uuid.uuid4()
    cloned_job = Job(
        id=job_id,
        source_path=source_job.source_path,
        source_name=source_job.source_name,
        file_hash=source_job.file_hash,
        status="pending",
        error_message=None,
        workflow_template=workflow_template or source_job.workflow_template,
        output_dir=source_job.output_dir,
        config_profile_id=source_job.config_profile_id,
        config_profile_snapshot_json=dict(source_job.config_profile_snapshot_json or {}) or None,
        packaging_snapshot_json=dict(source_job.packaging_snapshot_json or {}) or None,
        language=language or source_job.language,
        workflow_mode=source_job.workflow_mode,
        enhancement_modes=list(source_job.enhancement_modes or []),
    )
    session.add(cloned_job)
    step_map: dict[str, JobStep] = {}
    now = datetime.now(timezone.utc)
    for step in create_job_steps(job_id):
        if step.step_name in {"probe", "extract_audio", "transcribe", "subtitle_postprocess"} and (
            media_meta_artifact is not None or transcript_rows or subtitle_rows or audio_artifact is not None
        ):
            step.status = "done"
            step.started_at = now
            step.finished_at = now
            step.metadata_ = {
                "detail": f"cloned_from:{source_job.id}",
                "progress": 1.0,
                "label": step.step_name,
                "updated_at": now.isoformat(),
            }
        session.add(step)
        step_map[step.step_name] = step

    if media_meta_artifact is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map.get("probe").id if step_map.get("probe") else None,
                artifact_type="media_meta",
                storage_path=media_meta_artifact.storage_path,
                data_json=dict(media_meta_artifact.data_json or {}) or None,
            )
        )
    if audio_artifact is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map.get("extract_audio").id if step_map.get("extract_audio") else None,
                artifact_type="audio_wav",
                storage_path=audio_artifact.storage_path,
                data_json=dict(audio_artifact.data_json or {}) or None,
            )
        )
    for row in transcript_rows:
        session.add(
            TranscriptSegment(
                job_id=job_id,
                version=row.version,
                segment_index=row.segment_index,
                start_time=row.start_time,
                end_time=row.end_time,
                speaker=row.speaker,
                text=row.text,
                words_json=list(row.words_json or []),
            )
        )
    for row in subtitle_rows:
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=row.version,
                item_index=row.item_index,
                start_time=row.start_time,
                end_time=row.end_time,
                text_raw=row.text_raw,
                text_norm=row.text_norm,
                text_final=row.text_final,
            )
        )

    rerun_mode = "cloned_profile_only" if transcript_rows and subtitle_rows else "cloned_full_chain"
    return job_id, rerun_mode


def run_job_steps(job_id: str, *, steps: list[str]) -> None:
    for step_name in steps:
        mark_step(job_id, step_name, "running")
        try:
            run_step_sync(step_name, job_id)
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            mark_step(job_id, step_name, "failed", error=error_text)
            finalize_job(job_id, status="failed", error=error_text)
            raise
        mark_step(job_id, step_name, "done")


def mark_step(job_id: str, step_name: str, status: str, *, error: str | None = None) -> None:
    async def _update() -> None:
        factory = get_session_factory()
        async with factory() as session:
            step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == step_name)
                )
            ).scalar_one()
            now = datetime.now(timezone.utc)
            step.status = status
            if status == "running":
                step.started_at = now
                step.finished_at = None
                step.error_message = None
            elif status in {"done", "failed", "cancelled"}:
                step.finished_at = now
                step.error_message = error
            await session.commit()

    asyncio.run(_update())


def finalize_job(job_id: str, *, status: str, error: str | None = None) -> None:
    async def _finalize() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            if job is None:
                return
            job.status = status
            job.error_message = error
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()

    asyncio.run(_finalize())


async def collect_row_report(
    *,
    source_name: str,
    job_id: str,
    rerun_mode: str,
    error: str | None = None,
) -> RowReport:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        profile_artifact = (
            await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job_uuid,
                    Artifact.artifact_type.in_(["content_profile", "content_profile_draft", "content_profile_final"]),
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().first()
        correction_rows = (
            await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid))
        ).scalars().all()
        profile = dict((profile_artifact.data_json if profile_artifact else None) or {})
        verification_gate = dict(profile.get("verification_gate") or {})
        review_reasons = [
            str(item).strip()
            for item in list(profile.get("review_reasons") or verification_gate.get("review_reasons") or [])
            if str(item).strip()
        ]
        pending_corrections = sum(
            1 for item in correction_rows if item.human_decision not in {"accepted", "rejected"}
        )

        status = "failed" if error else "done"
        note_parts = [rerun_mode]
        if verification_gate.get("needs_review"):
            note_parts.append("verification_gate")
        note = ",".join(part for part in note_parts if part) or None
        return RowReport(
            source_name=source_name,
            status=status,
            job_id=job_id,
            rerun_mode=rerun_mode,
            summary=str(profile.get("summary") or "").strip() or None,
            subject_brand=str(profile.get("subject_brand") or "").strip() or None,
            subject_model=str(profile.get("subject_model") or "").strip() or None,
            subject_type=str(profile.get("subject_type") or "").strip() or None,
            video_theme=str(profile.get("video_theme") or "").strip() or None,
            subtitle_correction_count=len(correction_rows),
            pending_correction_count=pending_corrections,
            needs_review=bool(profile.get("needs_review") or verification_gate.get("needs_review")),
            review_reasons=review_reasons,
            verification_conflict_count=len(list(verification_gate.get("conflicts") or [])),
            verification_missing_supported_fields=[
                str(item).strip()
                for item in list(verification_gate.get("missing_supported_fields") or [])
                if str(item).strip()
            ],
            note=note,
            error=error,
        )


def load_baseline_metrics(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    metrics = dict(((data.get("assessment") or {}).get("metrics") or {}))
    return {
        "done_count": int(metrics.get("done_count") or data.get("done_count") or 0),
        "failed_count": int(metrics.get("failed_count") or data.get("failed_count") or 0),
        "skipped_count": int(metrics.get("skipped_count") or data.get("skipped_count") or 0),
        "brand_missing_among_done": int(metrics.get("brand_missing_among_done") or 0),
        "model_missing_among_done": int(metrics.get("model_missing_among_done") or 0),
        "zero_correction_among_done": int(metrics.get("zero_correction_among_done") or 0),
    }


def build_folder_items(source_dir: Path, files: list[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in files:
        stat = path.stat()
        items.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(source_dir)),
                "source_name": path.name,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
                "duration_sec": 0.0,
            }
        )
    return items


def render_markdown(report: dict[str, Any]) -> str:
    assessment = report.get("assessment") or {}
    metrics = assessment.get("metrics") or {}
    baseline = report.get("baseline_compare") or {}
    lines = [
        "# EDC Summary Regression Report",
        "",
        f"- created_at: {report.get('created_at')}",
        f"- folder: {report.get('folder')}",
        f"- total_files: {report.get('total_files')}",
        f"- done_count: {report.get('done_count')}",
        f"- failed_count: {report.get('failed_count')}",
        f"- skipped_count: {report.get('skipped_count')}",
        "",
        "## Metrics",
        "",
        f"- brand_missing_among_done: {metrics.get('brand_missing_among_done')}",
        f"- model_missing_among_done: {metrics.get('model_missing_among_done')}",
        f"- zero_correction_among_done: {metrics.get('zero_correction_among_done')}",
        f"- needs_review_among_done: {metrics.get('needs_review_among_done')}",
        "",
    ]
    if baseline:
        lines.extend(
            [
                "## Baseline Compare",
                "",
                f"- baseline_file: {baseline.get('baseline_file')}",
                f"- brand_missing_delta: {baseline.get('brand_missing_delta')}",
                f"- model_missing_delta: {baseline.get('model_missing_delta')}",
                f"- zero_correction_delta: {baseline.get('zero_correction_delta')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Merge Groups",
            "",
        ]
    )
    merge_groups = list(report.get("merge_groups") or [])
    if not merge_groups:
        lines.append("- none")
    else:
        for group in merge_groups:
            lines.append(
                f"- {', '.join(group.get('relative_paths') or [])} | score={group.get('score'):.2f} | reasons={', '.join(group.get('reasons') or [])}"
            )
    lines.extend(["", "## Rows", ""])
    for row in report.get("rows") or []:
        lines.append(f"### {row.get('source_name')}")
        lines.append(f"- status: {row.get('status')}")
        lines.append(f"- job_id: {row.get('job_id') or ''}")
        lines.append(f"- rerun_mode: {row.get('rerun_mode') or ''}")
        lines.append(f"- subject_brand: {row.get('subject_brand') or ''}")
        lines.append(f"- subject_model: {row.get('subject_model') or ''}")
        lines.append(f"- subject_type: {row.get('subject_type') or ''}")
        lines.append(f"- video_theme: {row.get('video_theme') or ''}")
        lines.append(f"- subtitle_correction_count: {row.get('subtitle_correction_count')}")
        lines.append(f"- pending_correction_count: {row.get('pending_correction_count')}")
        lines.append(f"- needs_review: {row.get('needs_review')}")
        if row.get("review_reasons"):
            lines.append(f"- review_reasons: {' / '.join(row.get('review_reasons') or [])}")
        if row.get("summary"):
            lines.append(f"- summary: {row.get('summary')}")
        if row.get("error"):
            lines.append(f"- error: {row.get('error')}")
        if row.get("note"):
            lines.append(f"- note: {row.get('note')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir
    files = list_source_files(
        source_dir,
        limit=max(0, int(args.limit or 0)),
        samples=list(args.samples or []),
    )
    if not files:
        raise SystemExit(f"No source videos found in {source_dir}")

    rows: list[RowReport] = []
    started_at = datetime.now(timezone.utc).isoformat()
    folder_items = build_folder_items(source_dir, files)
    merge_groups = asyncio.run(suggest_merge_groups_for_inventory_items(folder_items))

    for index, path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] {path.name}", flush=True)
        if "已剪" in path.stem or "已剪辑" in path.stem:
            rows.append(
                RowReport(
                    source_name=path.name,
                    status="skipped_edited",
                    job_id=None,
                    rerun_mode=None,
                    summary=None,
                    subject_brand=None,
                    subject_model=None,
                    subject_type=None,
                    video_theme=None,
                    subtitle_correction_count=None,
                    pending_correction_count=None,
                    needs_review=None,
                    review_reasons=[],
                    verification_conflict_count=None,
                    verification_missing_supported_fields=[],
                    note="filename_marked_edited",
                )
            )
            continue

        job_id = ""
        rerun_mode = ""
        error_text: str | None = None
        try:
            job_id, rerun_mode = asyncio.run(
                clone_or_prepare_job_for_source(
                    path,
                    workflow_template=args.workflow_template,
                    language=args.language,
                )
            )
            steps = PROFILE_STEPS if rerun_mode == "cloned_profile_only" else FULL_CHAIN_STEPS
            run_job_steps(job_id, steps=steps)
            finalize_job(job_id, status="done")
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
        row = asyncio.run(
            collect_row_report(
                source_name=path.name,
                job_id=job_id,
                rerun_mode=rerun_mode or "failed_before_job",
                error=error_text,
            )
        ) if job_id else RowReport(
            source_name=path.name,
            status="failed",
            job_id=None,
            rerun_mode=rerun_mode or "failed_before_job",
            summary=None,
            subject_brand=None,
            subject_model=None,
            subject_type=None,
            video_theme=None,
            subtitle_correction_count=None,
            pending_correction_count=None,
            needs_review=None,
            review_reasons=[],
            verification_conflict_count=None,
            verification_missing_supported_fields=[],
            note=None,
            error=error_text,
        )
        rows.append(row)

    done_rows = [row for row in rows if row.status == "done"]
    failed_rows = [row for row in rows if row.status == "failed"]
    skipped_rows = [row for row in rows if row.status.startswith("skipped")]
    metrics = {
        "done_count": len(done_rows),
        "failed_count": len(failed_rows),
        "skipped_count": len(skipped_rows),
        "brand_missing_among_done": sum(1 for row in done_rows if not str(row.subject_brand or "").strip()),
        "model_missing_among_done": sum(1 for row in done_rows if not str(row.subject_model or "").strip()),
        "zero_correction_among_done": sum(
            1 for row in done_rows if int(row.subtitle_correction_count or 0) <= 0
        ),
        "needs_review_among_done": sum(1 for row in done_rows if bool(row.needs_review)),
    }
    baseline_metrics = load_baseline_metrics(args.baseline_json)
    baseline_compare = {}
    if baseline_metrics:
        baseline_compare = {
            "baseline_file": str(args.baseline_json),
            "brand_missing_delta": metrics["brand_missing_among_done"] - baseline_metrics.get("brand_missing_among_done", 0),
            "model_missing_delta": metrics["model_missing_among_done"] - baseline_metrics.get("model_missing_among_done", 0),
            "zero_correction_delta": metrics["zero_correction_among_done"] - baseline_metrics.get("zero_correction_among_done", 0),
        }

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "folder": str(source_dir),
        "total_files": len(files),
        "done_count": len(done_rows),
        "failed_count": len(failed_rows),
        "skipped_count": len(skipped_rows),
        "merge_groups": merge_groups,
        "assessment": {
            "metrics": metrics,
        },
        "baseline_compare": baseline_compare,
        "rows": [asdict(row) for row in rows],
    }

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / f"{args.report_prefix}_{timestamp}.json"
    md_path = args.report_dir / f"{args.report_prefix}_{timestamp}.md"
    merge_path = args.report_dir / f"raw_merge_groups_{args.report_prefix}_{timestamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    merge_path.write_text(json.dumps(merge_groups, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "merge_report": str(merge_path),
                "metrics": metrics,
                "baseline_compare": baseline_compare,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
