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
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import select

from roughcut.config import _normalize_settings, get_settings
from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import PIPELINE_STEPS
from roughcut.pipeline.steps import run_step_sync
from roughcut.review.subtitle_consistency import ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT
from roughcut.review.subtitle_term_resolution import ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER
from run_fullchain_batch import (
    StepRun,
    auto_confirm_content_profile,
    compute_keep_ratio,
    finalize_job,
    mark_step,
    prepare_job_for_source,
    read_step_detail,
)


TARGET_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "subtitle_term_resolution",
    "subtitle_consistency_review",
    "glossary_review",
    "transcript_review",
    "subtitle_translation",
    "content_profile",
    "summary_review",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "final_review",
    "platform_package",
]


@dataclass
class ProviderSpec:
    provider: str
    model: str
    label: str


@dataclass
class StageScore:
    name: str
    score: float
    rationale: str


@dataclass
class RunSummary:
    provider: str
    model: str
    label: str
    job_id: str
    status: str
    total_elapsed_seconds: float
    step_runs: list[dict[str, Any]]
    stage_scores: list[dict[str, Any]]
    overall_score: float
    subtitle_count: int
    transcript_segment_count: int
    correction_count: int
    keep_ratio: float
    issue_codes: list[str]
    content_profile: dict[str, Any]
    packaging_excerpt: dict[str, Any]
    packaging_path: str | None


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
    parser = argparse.ArgumentParser(description="Run renderless RoughCut provider comparison on local videos.")
    parser.add_argument("--source", action="append", dest="sources", default=[], help="Absolute or repo-relative video path.")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / "provider-compare")
    parser.add_argument("--output-dir", default="F:/roughcut_outputs/output/provider_compare")
    parser.add_argument("--workflow-template", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument(
        "--enhancement-mode",
        action="append",
        dest="enhancement_modes",
        default=["avatar_commentary", "ai_effects", "multi_platform_adaptation"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = [resolve_source_path(Path(raw)) for raw in args.sources]
    if not sources:
        raise SystemExit("At least one --source is required")

    report_root = args.report_dir / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_root.mkdir(parents=True, exist_ok=True)

    providers = [
        ProviderSpec(provider="openai", model="gpt-5.4", label="OpenAI GPT-5.4"),
        ProviderSpec(provider="minimax", model="MiniMax-M2.7", label="MiniMax M2.7"),
    ]
    samples: list[dict[str, Any]] = []
    for source in sources:
        sample_runs: list[RunSummary] = []
        for provider in providers:
            run = execute_provider_run(
                source_path=source,
                provider=provider,
                output_dir=args.output_dir,
                workflow_template=args.workflow_template,
                language=args.language,
                enhancement_modes=list(dict.fromkeys(args.enhancement_modes)),
            )
            sample_runs.append(run)
        samples.append(
            {
                "source_path": str(source),
                "source_name": source.name,
                "runs": [asdict(item) for item in sample_runs],
            }
        )

    report = build_report(samples)
    json_path = report_root / "provider_comparison_report.json"
    md_path = report_root / "provider_comparison_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))


def resolve_source_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else (ROOT / path)
    candidate = candidate.resolve()
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return candidate


def execute_provider_run(
    *,
    source_path: Path,
    provider: ProviderSpec,
    output_dir: str,
    workflow_template: str,
    language: str,
    enhancement_modes: list[str],
) -> RunSummary:
    with temporary_settings(
        llm_mode="performance",
        llm_routing_mode="bundled",
        reasoning_provider=provider.provider,
        reasoning_model=provider.model,
    ):
        job_id = asyncio.run(
            prepare_job_for_source(
                source_path,
                channel_profile=workflow_template,
                language=language,
                output_dir=output_dir,
                enhancement_modes=enhancement_modes,
                force_rerun_existing=True,
            )
        )
        if not job_id:
            raise RuntimeError(f"Failed to prepare job for {source_path}")
        step_runs, status = run_job_renderless(job_id)
        finalize_job(job_id, "done" if status == "done" else status)
        return asyncio.run(collect_run_summary(job_id, provider, step_runs, status))


def run_job_renderless(job_id: str) -> tuple[list[StepRun], str]:
    step_runs: list[StepRun] = []
    status = "done"
    for step_name in TARGET_STEPS:
        if step_name == "summary_review":
            started = time.perf_counter()
            auto_confirm_content_profile(job_id)
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=read_step_detail(job_id, step_name),
                )
            )
            continue

        if step_name in {"render", "final_review", "ai_director", "avatar_commentary"}:
            started = time.perf_counter()
            mark_step(job_id, step_name, "skipped")
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="skipped",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=f"{step_name} skipped for renderless comparison.",
                )
            )
            continue

        started = time.perf_counter()
        mark_step(job_id, step_name, "running")
        try:
            run_step_sync(step_name, job_id)
            mark_step(job_id, step_name, "done")
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=read_step_detail(job_id, step_name),
                )
            )
        except Exception as exc:
            status = "failed"
            error_text = f"{type(exc).__name__}: {exc}"
            mark_step(job_id, step_name, "failed", error=error_text)
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="failed",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=error_text,
                )
            )
            break

    return step_runs, status


async def collect_run_summary(
    job_id: str,
    provider: ProviderSpec,
    step_runs: list[StepRun],
    status: str,
) -> RunSummary:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        job = await session.get(Job, job_uuid)
        subtitles = (await session.execute(select(SubtitleItem).where(SubtitleItem.job_id == job_uuid, SubtitleItem.version == 1))).scalars().all()
        transcripts = (await session.execute(select(TranscriptSegment).where(TranscriptSegment.job_id == job_uuid, TranscriptSegment.version == 1))).scalars().all()
        corrections = (await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid))).scalars().all()
        steps = (await session.execute(select(JobStep).where(JobStep.job_id == job_uuid))).scalars().all()
        artifacts = (await session.execute(select(Artifact).where(Artifact.job_id == job_uuid).order_by(Artifact.created_at.desc(), Artifact.id.desc()))).scalars().all()
        timelines = (await session.execute(select(Timeline).where(Timeline.job_id == job_uuid, Timeline.timeline_type == "editorial"))).scalars().all()
        render_outputs = (await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_uuid))).scalars().all()

    artifact_map = latest_artifact_map(artifacts)
    profile = artifact_payload(artifact_map.get("content_profile_final")) or artifact_payload(artifact_map.get("content_profile")) or artifact_payload(artifact_map.get("content_profile_draft"))
    packaging_payload = artifact_payload(artifact_map.get("platform_packaging_md"))
    subtitle_quality = artifact_payload(artifact_map.get(ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT))
    term_resolution = artifact_payload(artifact_map.get(ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH))
    consistency = artifact_payload(artifact_map.get(ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT))
    subtitle_projection = artifact_payload(artifact_map.get(ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER))
    editorial = timelines[0].data_json if timelines else {}
    keep_ratio = round(compute_keep_ratio(editorial), 3)

    stage_scores = [
        score_subtitles(subtitle_quality, term_resolution, consistency),
        score_content_profile(profile),
        score_edit_plan(editorial, keep_ratio=keep_ratio),
        score_platform_packaging(packaging_payload),
    ]
    overall_score = round(sum(item.score for item in stage_scores) / len(stage_scores), 1)
    issue_codes = collect_issue_codes(stage_scores, step_runs, render_outputs)
    packaging_path = str(getattr(artifact_map.get("platform_packaging_md"), "storage_path", "") or "").strip() or None

    packaging_excerpt = {
        "generation_mode": str(packaging_payload.get("generation_mode") or "").strip(),
        "generation_note": str(packaging_payload.get("generation_note") or "").strip(),
        "highlights": {
            "product": str(((packaging_payload.get("highlights") or {}).get("product") or "")).strip(),
            "title_hook": str(((packaging_payload.get("highlights") or {}).get("title_hook") or "")).strip(),
            "engagement_question": str(((packaging_payload.get("highlights") or {}).get("engagement_question") or "")).strip(),
        },
        "douyin_titles": list((((packaging_payload.get("platforms") or {}).get("douyin") or {}).get("titles") or []))[:3],
        "xiaohongshu_titles": list((((packaging_payload.get("platforms") or {}).get("xiaohongshu") or {}).get("titles") or []))[:3],
    }
    effective_subtitle_count = len(list(subtitle_projection.get("entries") or [])) or len(subtitles)

    return RunSummary(
        provider=provider.provider,
        model=provider.model,
        label=provider.label,
        job_id=job_id,
        status=status,
        total_elapsed_seconds=round(sum(item.elapsed_seconds for item in step_runs), 3),
        step_runs=[asdict(item) for item in step_runs],
        stage_scores=[asdict(item) for item in stage_scores],
        overall_score=overall_score,
        subtitle_count=effective_subtitle_count,
        transcript_segment_count=len(transcripts),
        correction_count=len(corrections),
        keep_ratio=keep_ratio,
        issue_codes=issue_codes,
        content_profile=profile,
        packaging_excerpt=packaging_excerpt,
        packaging_path=packaging_path,
    )


def latest_artifact_map(artifacts: list[Artifact]) -> dict[str, Artifact]:
    result: dict[str, Artifact] = {}
    for artifact in artifacts:
        if artifact.artifact_type not in result:
            result[artifact.artifact_type] = artifact
    return result


def artifact_payload(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None or not isinstance(artifact.data_json, dict):
        return {}
    return dict(artifact.data_json)


def clamp(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def score_subtitles(
    subtitle_quality: dict[str, Any],
    term_resolution: dict[str, Any],
    consistency: dict[str, Any],
) -> StageScore:
    score = 100.0
    reasons: list[str] = []
    pending_terms = int(((term_resolution.get("metrics") or {}).get("pending_count") or 0))
    if pending_terms:
        score -= min(25.0, pending_terms * 4.0)
        reasons.append(f"待人工确认术语 {pending_terms} 处")
    if bool(subtitle_quality.get("blocking")):
        score -= 22.0
        reasons.append("字幕质量存在 blocking")
    warning_count = len(list(subtitle_quality.get("warning_reasons") or []))
    if warning_count:
        score -= min(12.0, warning_count * 3.0)
        reasons.append(f"字幕质量 warning {warning_count} 项")
    if bool(consistency.get("blocking")):
        score -= 18.0
        reasons.append("一致性存在 blocking")
    consistency_warning_count = len(list(consistency.get("warning_reasons") or []))
    if consistency_warning_count:
        score -= min(10.0, consistency_warning_count * 2.0)
        reasons.append(f"一致性 warning {consistency_warning_count} 项")
    if not reasons:
        reasons.append("字幕链路通过，无明显术语/一致性阻塞")
    return StageScore(name="subtitle_chain", score=clamp(score), rationale="；".join(reasons))


def score_content_profile(profile: dict[str, Any]) -> StageScore:
    score = 78.0
    reasons: list[str] = []
    if not profile:
        return StageScore(name="content_profile", score=0.0, rationale="未产出内容画像")
    automation_score = float(((profile.get("automation_review") or {}).get("score") or 0.0))
    if automation_score > 0:
        score = max(score, automation_score * 100.0)
        reasons.append(f"自动评审分 {automation_score:.2f}")
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary"):
        if str(profile.get(key) or "").strip():
            score += 2.0
        else:
            score -= 8.0
            reasons.append(f"缺少 {key}")
    review_mode = str(profile.get("review_mode") or "").strip()
    if review_mode:
        reasons.append(f"review_mode={review_mode}")
    return StageScore(name="content_profile", score=clamp(score), rationale="；".join(reasons) or "画像字段齐全")


def score_edit_plan(editorial: dict[str, Any], *, keep_ratio: float) -> StageScore:
    if not editorial:
        return StageScore(name="edit_plan", score=0.0, rationale="未产出 editorial timeline")
    score = 82.0
    reasons = [f"keep_ratio={keep_ratio:.3f}"]
    segments = list(editorial.get("segments") or [])
    if len(segments) < 2:
        score -= 18.0
        reasons.append("时间轴分段过少")
    if keep_ratio < 0.15 or keep_ratio > 0.92:
        score -= 12.0
        reasons.append("保留比例异常")
    return StageScore(name="edit_plan", score=clamp(score), rationale="；".join(reasons))


def score_platform_packaging(packaging: dict[str, Any]) -> StageScore:
    if not packaging:
        return StageScore(name="platform_package", score=0.0, rationale="未产出平台文案")
    score = 84.0
    reasons: list[str] = []
    generation_mode = str(packaging.get("generation_mode") or "").strip()
    if generation_mode:
        reasons.append(f"mode={generation_mode}")
    title_audit = packaging.get("title_audit") if isinstance(packaging.get("title_audit"), dict) else {}
    summary = title_audit.get("summary") if isinstance(title_audit.get("summary"), dict) else {}
    errors = int(summary.get("platforms_with_errors") or 0)
    warnings = int(summary.get("platforms_with_warnings") or 0)
    if errors:
        score -= min(24.0, errors * 8.0)
        reasons.append(f"标题审计报错平台 {errors}")
    if warnings:
        score -= min(12.0, warnings * 3.0)
        reasons.append(f"标题审计预警平台 {warnings}")
    platform_count = len(list((packaging.get("platforms") or {}).keys()))
    if platform_count:
        score += min(8.0, platform_count * 2.0)
        reasons.append(f"平台文案覆盖 {platform_count} 个平台")
    return StageScore(name="platform_package", score=clamp(score), rationale="；".join(reasons) or "文案产出正常")


def collect_issue_codes(stage_scores: list[StageScore], step_runs: list[StepRun], render_outputs: list[RenderOutput]) -> list[str]:
    issues: list[str] = []
    for stage in stage_scores:
        if stage.score < 70:
            issues.append(f"{stage.name}_low_score")
    for step in step_runs:
        if step.status == "failed":
            issues.append(f"{step.step}_failed")
    if not any(str(output.status or "").lower() == "done" for output in render_outputs):
        issues.append("render_skipped_by_design")
    return issues


def build_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {
        "openai": {"overall": [], "elapsed": [], "subtitle": [], "profile": [], "edit": [], "packaging": []},
        "minimax": {"overall": [], "elapsed": [], "subtitle": [], "profile": [], "edit": [], "packaging": []},
    }
    for sample in samples:
        for run in sample["runs"]:
            bucket = aggregate[run["provider"]]
            bucket["overall"].append(float(run["overall_score"]))
            bucket["elapsed"].append(float(run["total_elapsed_seconds"]))
            stage_map = {item["name"]: float(item["score"]) for item in run["stage_scores"]}
            bucket["subtitle"].append(stage_map.get("subtitle_chain", 0.0))
            bucket["profile"].append(stage_map.get("content_profile", 0.0))
            bucket["edit"].append(stage_map.get("edit_plan", 0.0))
            bucket["packaging"].append(stage_map.get("platform_package", 0.0))

    summary = {}
    for provider, bucket in aggregate.items():
        summary[provider] = {key: round(sum(values) / len(values), 2) if values else 0.0 for key, values in bucket.items()}

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples),
        "samples": samples,
        "summary": summary,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RoughCut Renderless Provider Comparison",
        "",
        f"- created_at: {report.get('created_at')}",
        f"- sample_count: {report.get('sample_count')}",
        "- scope: model-sensitive steps only, render and final_review excluded by design",
        "",
        "## Aggregate",
        "",
    ]
    summary = report.get("summary") or {}
    for provider in ("openai", "minimax"):
        provider_summary = summary.get(provider) or {}
        lines.extend(
            [
                f"### {provider}",
                f"- overall_score: {provider_summary.get('overall', 0.0)}",
                f"- total_elapsed_seconds: {provider_summary.get('elapsed', 0.0)}",
                f"- subtitle_chain: {provider_summary.get('subtitle', 0.0)}",
                f"- content_profile: {provider_summary.get('profile', 0.0)}",
                f"- edit_plan: {provider_summary.get('edit', 0.0)}",
                f"- platform_package: {provider_summary.get('packaging', 0.0)}",
                "",
            ]
        )

    lines.append("## Per Sample")
    lines.append("")
    for sample in report.get("samples") or []:
        lines.append(f"### {sample.get('source_name')}")
        lines.append(f"- source_path: {sample.get('source_path')}")
        runs = sample.get("runs") or []
        for run in runs:
            lines.append(f"#### {run.get('label')}")
            lines.append(
                f"- status: {run.get('status')} | overall_score: {run.get('overall_score')} | elapsed: {run.get('total_elapsed_seconds')}s"
            )
            lines.append(
                f"- issue_codes: {', '.join(run.get('issue_codes') or []) or '-'}"
            )
            lines.append(
                f"- content_profile: brand={str((run.get('content_profile') or {}).get('subject_brand') or '')} | "
                f"model={str((run.get('content_profile') or {}).get('subject_model') or '')} | "
                f"theme={str((run.get('content_profile') or {}).get('video_theme') or '')}"
            )
            excerpt = run.get("packaging_excerpt") or {}
            lines.append(
                f"- packaging_mode: {excerpt.get('generation_mode') or '-'} | title_hook: {str((excerpt.get('highlights') or {}).get('title_hook') or '')}"
            )
            for stage in run.get("stage_scores") or []:
                lines.append(f"- {stage.get('name')}: {stage.get('score')} ({stage.get('rationale')})")
            titles = list(excerpt.get("douyin_titles") or [])[:2]
            if titles:
                lines.append(f"- douyin_titles: {' | '.join(str(item) for item in titles)}")
            titles = list(excerpt.get("xiaohongshu_titles") or [])[:2]
            if titles:
                lines.append(f"- xiaohongshu_titles: {' | '.join(str(item) for item in titles)}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
