from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from roughcut.config import get_settings
from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.pipeline.steps import run_step_sync
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths
from tests.fixtures.content_understanding_benchmark_samples import BENCHMARK_SAMPLES

PIPELINE_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "content_profile",
]


@dataclass
class SampleRunReport:
    source_name: str
    source_path: str
    expected_product_family: str
    expected_keywords: list[str]
    keyword_hits: list[str]
    keyword_misses: list[str]
    job_id: str
    status: str
    transcript_segment_count: int
    subtitle_count: int
    content_subject: str
    content_kind: str
    subject_type: str
    video_theme: str
    observed_entities: list[dict[str, Any]]
    resolved_entities: list[dict[str, Any]]
    resolved_primary_subject: str
    conflicts: list[Any]
    capability_matrix: dict[str, Any]
    needs_review: bool | None
    review_reasons: list[str]
    elapsed_seconds: float
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a repeatable content-understanding benchmark on curated product samples.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(r"Y:\EDC系列\未剪辑视频"),
        help="Directory containing the benchmark source videos.",
    )
    parser.add_argument(
        "--samples",
        nargs="*",
        default=[],
        help="Optional explicit source_name values. Defaults to BENCHMARK_SAMPLES fixture order.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=4,
        help="How many samples to run from the curated fixture list.",
    )
    parser.add_argument(
        "--channel-profile",
        default="edc_tactical",
        help="Channel profile used when creating benchmark jobs.",
    )
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "output" / "test" / "content-understanding-benchmark",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    samples = resolve_samples(args.source_dir, args.samples, args.limit)
    if not samples:
        raise SystemExit("No benchmark samples resolved.")

    reports: list[SampleRunReport] = []
    for sample in samples:
        started = time.perf_counter()
        try:
            job_id = asyncio.run(
                prepare_job_for_source(
                    sample["source_path"],
                    channel_profile=args.channel_profile,
                    language=args.language,
                )
            )
            run_job_to_content_profile(job_id)
            report = asyncio.run(collect_sample_report(job_id, sample, time.perf_counter() - started))
            reports.append(report)
            print(
                json.dumps(
                    {
                        "source_name": report.source_name,
                        "job_id": report.job_id,
                        "subject_type": report.subject_type,
                        "video_theme": report.video_theme,
                        "resolved_primary_subject": report.resolved_primary_subject,
                        "keyword_hits": report.keyword_hits,
                        "needs_review": report.needs_review,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            reports.append(
                SampleRunReport(
                    source_name=sample["source_name"],
                    source_path=str(sample["source_path"]),
                    expected_product_family=sample["expected_product_family"],
                    expected_keywords=list(sample["expected_keywords"]),
                    keyword_hits=[],
                    keyword_misses=list(sample["expected_keywords"]),
                    job_id="",
                    status="failed",
                    transcript_segment_count=0,
                    subtitle_count=0,
                    content_subject="",
                    content_kind="",
                    subject_type="",
                    video_theme="",
                    observed_entities=[],
                    resolved_entities=[],
                    resolved_primary_subject="",
                    conflicts=[],
                    capability_matrix={},
                    needs_review=None,
                    review_reasons=[],
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "channel_profile": args.channel_profile,
        "language": args.language,
        "sample_count": len(reports),
        "success_count": sum(1 for item in reports if item.status == "done"),
        "failed_count": sum(1 for item in reports if item.status != "done"),
        "reports": [asdict(item) for item in reports],
    }
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = args.report_dir / f"content_understanding_benchmark_{timestamp}.json"
    md_path = args.report_dir / f"content_understanding_benchmark_{timestamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {json_path}", flush=True)
    print(f"Markdown report: {md_path}", flush=True)


def resolve_samples(source_dir: Path, explicit_names: list[str], limit: int) -> list[dict[str, Any]]:
    names = explicit_names or [str(item["source_name"]) for item in BENCHMARK_SAMPLES[:limit]]
    fixture_map = {str(item["source_name"]): item for item in BENCHMARK_SAMPLES}
    resolved: list[dict[str, Any]] = []
    for name in names:
        fixture = fixture_map.get(name)
        if fixture is None:
            continue
        source_path = source_dir / name
        if not source_path.exists():
            continue
        resolved.append(
            {
                "source_name": name,
                "source_path": source_path,
                "expected_product_family": str(fixture["expected_product_family"]),
                "expected_keywords": list(fixture["expected_keywords"]),
            }
        )
    return resolved[:limit]


async def prepare_job_for_source(source_path: Path, *, channel_profile: str, language: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job).where(Job.source_name == source_path.name).order_by(Job.created_at.desc())
        )
        reusable = result.scalars().first()
        if reusable is not None:
            step_result = await session.execute(select(JobStep).where(JobStep.job_id == reusable.id))
            for step in step_result.scalars().all():
                if step.step_name in PIPELINE_STEPS:
                    step.status = "pending"
                    step.error_message = None
                    step.started_at = None
                    step.finished_at = None
                    step.metadata_ = None
            reusable.status = "pending"
            reusable.error_message = None
            reusable.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return str(reusable.id)

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        channel_profile=channel_profile,
        language=language,
    )
    job_id = str(created[0].get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"Failed to create benchmark job for {source_path.name}")
    return job_id


def run_job_to_content_profile(job_id: str) -> None:
    for step_name in PIPELINE_STEPS:
        mark_step(job_id, step_name, "running")
        try:
            run_step_sync(step_name, job_id)
        except Exception as exc:
            mark_step(job_id, step_name, "failed", error=f"{type(exc).__name__}: {exc}")
            finalize_job(job_id, "failed", error=f"{step_name}: {type(exc).__name__}: {exc}")
            raise
        mark_step(job_id, step_name, "done")
    finalize_job(job_id, "done")


def mark_step(job_id: str, step_name: str, status: str, *, error: str | None = None) -> None:
    async def _update() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
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


def finalize_job(job_id: str, status: str, *, error: str | None = None) -> None:
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


async def collect_sample_report(job_id: str, sample: dict[str, Any], elapsed_seconds: float) -> SampleRunReport:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        job = await session.get(Job, job_uuid)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        transcript_rows = (
            await session.execute(select(TranscriptSegment).where(TranscriptSegment.job_id == job_uuid, TranscriptSegment.version == 1))
        ).scalars().all()
        subtitle_rows = (
            await session.execute(select(SubtitleItem).where(SubtitleItem.job_id == job_uuid, SubtitleItem.version == 1))
        ).scalars().all()
        profile_artifact = (
            await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_uuid, Artifact.artifact_type.in_(["content_profile_draft", "content_profile"]))
                .order_by(Artifact.created_at.desc())
            )
        ).scalars().first()

        data = (profile_artifact.data_json if profile_artifact else {}) or {}
        understanding = data.get("content_understanding") or {}
        text_blob = " ".join(
            filter(
                None,
                [
                    str(data.get("content_subject") or ""),
                    str(data.get("subject_type") or ""),
                    str(data.get("video_theme") or ""),
                    str(understanding.get("resolved_primary_subject") or ""),
                    json.dumps(understanding.get("observed_entities") or [], ensure_ascii=False),
                    json.dumps(understanding.get("resolved_entities") or [], ensure_ascii=False),
                ],
            )
        )
        expected_keywords = list(sample["expected_keywords"])
        keyword_hits = [item for item in expected_keywords if item.lower() in text_blob.lower()]
        keyword_misses = [item for item in expected_keywords if item not in keyword_hits]
        review_reasons = [str(item).strip() for item in list(understanding.get("review_reasons") or []) if str(item).strip()]

        return SampleRunReport(
            source_name=sample["source_name"],
            source_path=str(sample["source_path"]),
            expected_product_family=sample["expected_product_family"],
            expected_keywords=expected_keywords,
            keyword_hits=keyword_hits,
            keyword_misses=keyword_misses,
            job_id=job_id,
            status=str(job.status or ""),
            transcript_segment_count=len(transcript_rows),
            subtitle_count=len(subtitle_rows),
            content_subject=str(data.get("content_subject") or ""),
            content_kind=str(data.get("content_kind") or ""),
            subject_type=str(data.get("subject_type") or ""),
            video_theme=str(data.get("video_theme") or ""),
            observed_entities=list(understanding.get("observed_entities") or []),
            resolved_entities=list(understanding.get("resolved_entities") or []),
            resolved_primary_subject=str(understanding.get("resolved_primary_subject") or ""),
            conflicts=list(understanding.get("conflicts") or []),
            capability_matrix=dict(understanding.get("capability_matrix") or {}),
            needs_review=understanding.get("needs_review"),
            review_reasons=review_reasons,
            elapsed_seconds=round(elapsed_seconds, 3),
        )


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Content Understanding Benchmark",
        "",
        f"- created_at: {summary['created_at']}",
        f"- source_dir: {summary['source_dir']}",
        f"- sample_count: {summary['sample_count']}",
        f"- success_count: {summary['success_count']}",
        f"- failed_count: {summary['failed_count']}",
        "",
        "| sample | expected_family | subject_type | resolved_primary_subject | keyword_hits | needs_review | status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in summary["reports"]:
        lines.append(
            "| {sample} | {family} | {subject} | {resolved} | {hits} | {review} | {status} |".format(
                sample=item["source_name"],
                family=item["expected_product_family"],
                subject=item["subject_type"] or "-",
                resolved=item["resolved_primary_subject"] or "-",
                hits=", ".join(item["keyword_hits"]) or "-",
                review=item["needs_review"],
                status=item["status"],
            )
        )
    return "\n".join(lines) + "\n"


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact_reports = []
    for item in summary["reports"]:
        compact_reports.append(
            {
                "source_name": item["source_name"],
                "expected_product_family": item["expected_product_family"],
                "keyword_hits": item["keyword_hits"],
                "keyword_misses": item["keyword_misses"],
                "observed_entities": item["observed_entities"],
                "resolved_entities": item["resolved_entities"],
                "conflicts": item["conflicts"],
                "capability_matrix": item["capability_matrix"],
                "subject_type": item["subject_type"],
                "resolved_primary_subject": item["resolved_primary_subject"],
                "needs_review": item["needs_review"],
                "status": item["status"],
                "elapsed_seconds": item["elapsed_seconds"],
                "error": item["error"],
            }
        )
    return {
        "sample_count": summary["sample_count"],
        "success_count": summary["success_count"],
        "failed_count": summary["failed_count"],
        "reports": compact_reports,
    }


if __name__ == "__main__":
    settings = get_settings()
    print(
        json.dumps(
            {
                "benchmark": "content_understanding",
                "database_url": settings.database_url,
                "reasoning_provider": settings.reasoning_provider,
                "research_verifier_enabled": bool(getattr(settings, "research_verifier_enabled", False)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    main()
