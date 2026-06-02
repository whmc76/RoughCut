from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.config import _normalize_settings, get_settings
from roughcut.db.models import Artifact, Job, SubtitleItem
from roughcut.db.session import get_session_factory
from roughcut.review.platform_copy import (
    build_packaging_prompt_brief,
    generate_platform_packaging,
)


REPORT_ROOT = ROOT / "output" / "test" / "m27-claim-grounded-packaging"


@dataclass
class RegressionRun:
    job_id: str
    source_name: str
    status: str
    elapsed_seconds: float
    subtitle_count: int
    claim_count: int
    unsupported_count: int
    repair_rounds: int
    title_hook: str
    douyin_titles: list[str]
    xiaohongshu_titles: list[str]
    error: str | None = None


@contextmanager
def temporary_settings(**updates: Any):
    settings = get_settings()
    backup = {key: getattr(settings, key) for key in updates}
    try:
        for key, value in updates.items():
            object.__setattr__(settings, key, value)
        _normalize_settings(settings)
        yield settings
    finally:
        for key, value in backup.items():
            object.__setattr__(settings, key, value)
        _normalize_settings(settings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MiniMax M2.7 claim-grounded platform packaging regression.")
    parser.add_argument("--job-id", action="append", default=[], help="Specific job id to evaluate. Can be repeated.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--report-dir", type=Path, default=REPORT_ROOT)
    parser.add_argument("--provider", default="minimax")
    parser.add_argument("--model", default="MiniMax-M2.7")
    parser.add_argument("--max-subtitles", type=int, default=80)
    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        help="Target platform key. Can be repeated. Default evaluates all platform_package platforms.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_dir = args.report_dir / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)

    with temporary_settings(
        llm_mode="performance",
        llm_routing_mode="bundled",
        reasoning_provider=args.provider,
        reasoning_model=args.model,
    ):
        runs = asyncio.run(run_regression(args, report_dir=report_dir))

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "copy_style": "m27_claim_grounded",
        "sample_count": len(runs),
        "runs": [asdict(item) for item in runs],
        "summary": summarize_runs(runs),
    }
    json_path = report_dir / "m27_claim_grounded_packaging_report.json"
    md_path = report_dir / "m27_claim_grounded_packaging_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))


async def run_regression(args: argparse.Namespace, *, report_dir: Path) -> list[RegressionRun]:
    jobs = await resolve_jobs(args.job_id, limit=args.limit)
    runs: list[RegressionRun] = []
    for job in jobs:
        run = await run_one_job(
            job,
            report_dir=report_dir,
            max_subtitles=max(1, int(args.max_subtitles or 80)),
            target_platforms=[str(item).strip() for item in args.platform if str(item).strip()] or None,
        )
        runs.append(run)
    return runs


async def resolve_jobs(job_ids: list[str], *, limit: int) -> list[Job]:
    factory = get_session_factory()
    async with factory() as session:
        if job_ids:
            jobs: list[Job] = []
            for raw in job_ids:
                job = await session.get(Job, uuid.UUID(str(raw)))
                if job is not None:
                    jobs.append(job)
            return jobs
        result = await session.execute(select(Job).order_by(Job.created_at.desc()).limit(max(limit * 3, limit)))
        candidates = list(result.scalars().all())
        selected: list[Job] = []
        for job in candidates:
            artifacts = await latest_artifact_map(session, job.id)
            if not (_artifact_payload(artifacts.get("content_profile_final")) or _artifact_payload(artifacts.get("content_profile"))):
                continue
            selected.append(job)
            if len(selected) >= limit:
                break
        return selected


async def run_one_job(
    job: Job,
    *,
    report_dir: Path,
    max_subtitles: int,
    target_platforms: list[str] | None,
) -> RegressionRun:
    started = time.perf_counter()
    try:
        content_profile, subtitle_items = await load_job_inputs(job.id, max_subtitles=max_subtitles)
        if not subtitle_items:
            raise RuntimeError("no subtitle items available")
        prompt_brief = build_packaging_prompt_brief(
            source_name=job.source_name,
            content_profile=content_profile,
            subtitle_items=subtitle_items,
        )
        fact_sheet = {
            "status": "unverified",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "本次回归只使用字幕和内容画像证据；禁止补充未在证据中出现的参数、结果、品类和经历。",
        }
        packaging = await generate_platform_packaging(
            source_name=job.source_name,
            content_profile=content_profile,
            subtitle_items=subtitle_items,
            copy_style="m27_claim_grounded",
            prompt_brief=prompt_brief,
            fact_sheet=fact_sheet,
            target_platforms=target_platforms,
        )
        out_path = report_dir / f"{job.id}_packaging.json"
        out_path.write_text(json.dumps(packaging, ensure_ascii=False, indent=2), encoding="utf-8")
        grounding = packaging.get("claim_grounding") if isinstance(packaging.get("claim_grounding"), dict) else {}
        ledger = grounding.get("claim_ledger") if isinstance(grounding.get("claim_ledger"), dict) else {}
        audit = grounding.get("audit") if isinstance(grounding.get("audit"), dict) else {}
        trace = list(grounding.get("trace") or [])
        platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
        highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
        return RegressionRun(
            job_id=str(job.id),
            source_name=str(job.source_name or ""),
            status="passed",
            elapsed_seconds=round(time.perf_counter() - started, 3),
            subtitle_count=len(subtitle_items),
            claim_count=len(list(ledger.get("claims") or [])),
            unsupported_count=len(list(audit.get("unsupported") or [])),
            repair_rounds=sum(1 for item in trace if item.get("stage") == "claim_grounding_round"),
            title_hook=str(highlights.get("title_hook") or ""),
            douyin_titles=[str(item) for item in ((platforms.get("douyin") or {}).get("titles") or [])[:3]],
            xiaohongshu_titles=[str(item) for item in ((platforms.get("xiaohongshu") or {}).get("titles") or [])[:3]],
        )
    except Exception as exc:
        return RegressionRun(
            job_id=str(job.id),
            source_name=str(job.source_name or ""),
            status="failed",
            elapsed_seconds=round(time.perf_counter() - started, 3),
            subtitle_count=0,
            claim_count=0,
            unsupported_count=0,
            repair_rounds=0,
            title_hook="",
            douyin_titles=[],
            xiaohongshu_titles=[],
            error=f"{type(exc).__name__}: {exc}",
        )


async def load_job_inputs(job_id: uuid.UUID, *, max_subtitles: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    factory = get_session_factory()
    async with factory() as session:
        artifacts = await latest_artifact_map(session, job_id)
        content_profile = (
            _artifact_payload(artifacts.get("content_profile_final"))
            or _artifact_payload(artifacts.get("content_profile"))
            or _artifact_payload(artifacts.get("content_profile_draft"))
        )
        projection = _artifact_payload(artifacts.get("subtitle_projection_layer"))
        entries = projection.get("entries") if isinstance(projection.get("entries"), list) else []
        if entries:
            subtitle_items = [normalize_subtitle_entry(item) for item in entries if isinstance(item, dict)]
        else:
            rows = (
                await session.execute(
                    select(SubtitleItem)
                    .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
                    .order_by(SubtitleItem.index.asc())
                    .limit(max_subtitles)
                )
            ).scalars().all()
            subtitle_items = [
                {
                    "index": int(row.index),
                    "start_time": float(row.start_time),
                    "end_time": float(row.end_time),
                    "text_raw": str(row.text_raw or ""),
                    "text_norm": str(row.text_norm or ""),
                    "text_final": str(row.text_final or row.text_norm or row.text_raw or ""),
                }
                for row in rows
            ]
        return content_profile, subtitle_items[:max_subtitles]


def normalize_subtitle_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(item.get("index") or 0),
        "start_time": float(item.get("start_time") or item.get("start") or 0.0),
        "end_time": float(item.get("end_time") or item.get("end") or item.get("start_time") or 0.0),
        "text_raw": str(item.get("text_raw") or item.get("text") or ""),
        "text_norm": str(item.get("text_norm") or item.get("text_final") or item.get("text") or ""),
        "text_final": str(item.get("text_final") or item.get("text_norm") or item.get("text") or ""),
    }


async def latest_artifact_map(session, job_id: uuid.UUID) -> dict[str, Artifact]:
    artifacts = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job_id)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().all()
    result: dict[str, Artifact] = {}
    for artifact in artifacts:
        if artifact.artifact_type not in result:
            result[artifact.artifact_type] = artifact
    return result


def _artifact_payload(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None or not isinstance(artifact.data_json, dict):
        return {}
    return dict(artifact.data_json)


def summarize_runs(runs: list[RegressionRun]) -> dict[str, Any]:
    passed = [run for run in runs if run.status == "passed"]
    failed = [run for run in runs if run.status != "passed"]
    return {
        "passed": len(passed),
        "failed": len(failed),
        "avg_elapsed_seconds": round(sum(run.elapsed_seconds for run in passed) / len(passed), 3) if passed else 0.0,
        "max_elapsed_seconds": max((run.elapsed_seconds for run in passed), default=0.0),
        "avg_claim_count": round(sum(run.claim_count for run in passed) / len(passed), 2) if passed else 0.0,
        "total_unsupported_after_repair": sum(run.unsupported_count for run in passed),
        "errors": [run.error for run in failed if run.error],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# MiniMax M2.7 Claim-Grounded Packaging Regression",
        "",
        f"- created_at: {report.get('created_at')}",
        f"- model: {report.get('provider')}/{report.get('model')}",
        f"- sample_count: {report.get('sample_count')}",
        f"- summary: {json.dumps(report.get('summary') or {}, ensure_ascii=False)}",
        "",
        "## Runs",
        "",
    ]
    for run in report.get("runs") or []:
        lines.append(f"### {run.get('source_name')}")
        lines.append(
            f"- status: {run.get('status')} | elapsed: {run.get('elapsed_seconds')}s | "
            f"claims: {run.get('claim_count')} | unsupported_after_repair: {run.get('unsupported_count')}"
        )
        if run.get("error"):
            lines.append(f"- error: {run.get('error')}")
        if run.get("title_hook"):
            lines.append(f"- hook: {run.get('title_hook')}")
        if run.get("douyin_titles"):
            lines.append(f"- douyin: {' | '.join(run.get('douyin_titles') or [])}")
        if run.get("xiaohongshu_titles"):
            lines.append(f"- xiaohongshu: {' | '.join(run.get('xiaohongshu_titles') or [])}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
