from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import select

from roughcut.config import apply_runtime_overrides, get_settings
from roughcut.db.models import Artifact, Job, JobStep
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.pipeline.steps import run_step_sync
from run_fullchain_batch import (
    StepRun,
    auto_confirm_content_profile,
    finalize_job,
    mark_step,
    prepare_job_for_source,
    read_step_detail,
)
from run_renderless_provider_comparison import ProviderSpec, build_report, collect_run_summary, render_markdown

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DEFAULT_SOURCE_ROOT = Path("F:/roughcut_outputs/jobs")
DEFAULT_WORK_ROOT = Path("F:/roughcut_outputs/provider_compare_inputs")
DEFAULT_OUTPUT_DIR = "F:/roughcut_outputs/output/provider_compare_batch"

RUN_STEPS = [
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 8-sample renderless provider A/B in parallel.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--source", action="append", dest="sources", default=[])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--parallel-jobs", type=int, default=4)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / "provider-compare")
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workflow-template", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--provider", action="append", default=[], help="provider:model:label")
    parser.add_argument("--worker-input", type=Path, default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker_input is not None:
        run_worker(args.worker_input)
        return

    providers = parse_providers(args.provider)
    sources = resolve_sources(args.source_root, args.sources, limit=args.limit)
    if len(sources) < args.limit:
        raise SystemExit(f"Only resolved {len(sources)} sources, required {args.limit}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = args.report_dir / f"parallel_renderless_ab_{run_id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    input_dir = args.work_root / run_id
    input_dir.mkdir(parents=True, exist_ok=True)

    all_samples: list[dict[str, Any]] = []
    for provider in providers:
        print(f"[provider] {provider.label} ({provider.provider}/{provider.model})", flush=True)
        apply_runtime_overrides(
            {
                "llm_mode": "performance",
                "llm_routing_mode": "bundled",
                "reasoning_provider": provider.provider,
                "reasoning_model": provider.model,
            }
        )
        clear_model_stage_caches()
        provider_sources = materialize_provider_sources(sources, input_dir=input_dir, provider=provider)
        provider_results = run_provider_batch(
            provider_sources,
            provider=provider,
            parallel_jobs=max(1, int(args.parallel_jobs or 1)),
            workflow_template=str(args.workflow_template),
            language=str(args.language),
            output_dir=str(args.output_dir),
            worker_dir=report_dir / "workers" / safe_name(provider.label.lower().replace(" ", "_"), max_len=36),
        )
        for result in provider_results:
            sample_key = result["sample_key"]
            sample = next((item for item in all_samples if item["sample_key"] == sample_key), None)
            if sample is None:
                sample = {
                    "sample_key": sample_key,
                    "source_path": result["original_source_path"],
                    "source_name": result["original_source_name"],
                    "runs": [],
                }
                all_samples.append(sample)
            sample["runs"].append(result["summary"])

    report = build_report(all_samples)
    report["run_id"] = run_id
    report["parallel_jobs"] = int(args.parallel_jobs or 1)
    report["cache_policy"] = "Cleared model-stage caches before each provider batch."
    json_path = report_dir / "parallel_provider_comparison_report.json"
    md_path = report_dir / "parallel_provider_comparison_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2), flush=True)


def parse_providers(raw_items: list[str]) -> list[ProviderSpec]:
    if not raw_items:
        return [
            ProviderSpec(provider="openai", model="gpt-5.4", label="OpenAI GPT-5.4"),
            ProviderSpec(provider="minimax", model="MiniMax-M2.7", label="MiniMax M2.7"),
        ]
    providers: list[ProviderSpec] = []
    for item in raw_items:
        parts = str(item).split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid provider spec {item!r}; expected provider:model:label")
        providers.append(ProviderSpec(provider=parts[0], model=parts[1], label=parts[2]))
    return providers


def resolve_sources(source_root: Path, explicit_sources: list[str], *, limit: int) -> list[Path]:
    if explicit_sources:
        candidates = [Path(item) for item in explicit_sources]
    else:
        candidates = [
            path
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ]
        candidates.sort(key=lambda path: (path.stat().st_mtime, str(path).lower()), reverse=True)
    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else (source_root / candidate)
        path = path.resolve()
        if not path.exists() or not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if is_provider_test_artifact(path):
            continue
        key = normalize_source_key(path.name)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)
        if len(resolved) >= limit:
            break
    return resolved


def is_provider_test_artifact(path: Path) -> bool:
    name = path.name.lower()
    if re.match(r"^\d{2}_(openai|mini|max|minimax)[_-]", name):
        return True
    if any(token in name for token in ("openai_gpt", "minimax_m", "minimax-m", "provider_compare")):
        return True
    return any("provider_compare" in part.lower() for part in path.parts)


def normalize_source_key(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"^(merged_\d+_)?", "", stem)
    stem = re.sub(r"[_\-\s]+", "", stem)
    return stem


def safe_name(value: str, *, max_len: int = 90) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value).strip(" ._")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned[:max_len].rstrip(" ._") or "sample")


def materialize_provider_sources(
    sources: list[Path],
    *,
    input_dir: Path,
    provider: ProviderSpec,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    label = safe_name(provider.label.lower().replace(" ", "_"), max_len=36)
    provider_dir = input_dir / label
    provider_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(sources, start=1):
        target = provider_dir / f"{index:02d}_{label}_{safe_name(source.stem)}{source.suffix.lower()}"
        if target.exists():
            target.unlink()
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        result.append(
            {
                "sample_key": f"sample_{index:02d}",
                "path": target,
                "original_source_path": str(source),
                "original_source_name": source.name,
            }
        )
    return result


def clear_model_stage_caches() -> None:
    cache_root = Path(get_settings().output_dir) / "_cache" / "llm"
    names = [
        "content_profile_enrich",
        "content_profile_infer",
        "edit_plan_cut_review",
        "platform_package_fact_sheet",
        "platform_package_generate",
    ]
    for name in names:
        path = cache_root / name
        resolved = path.resolve()
        expected = cache_root.resolve()
        if path.exists() and expected in resolved.parents:
            shutil.rmtree(path)


def run_provider_batch(
    sources: list[dict[str, Any]],
    *,
    provider: ProviderSpec,
    parallel_jobs: int,
    workflow_template: str,
    language: str,
    output_dir: str,
    worker_dir: Path,
) -> list[dict[str, Any]]:
    worker_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_jobs) as executor:
        futures = {
            executor.submit(
                run_worker_subprocess,
                source,
                provider=provider,
                workflow_template=workflow_template,
                language=language,
                output_dir=output_dir,
                worker_dir=worker_dir,
            ): source
            for source in sources
        }
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                results.append(future.result())
                print(f"[done] {provider.label} {source['sample_key']} {source['original_source_name']}", flush=True)
            except Exception as exc:
                print(f"[failed] {provider.label} {source['sample_key']} {type(exc).__name__}: {exc}", flush=True)
                results.append(
                    {
                        "sample_key": source["sample_key"],
                        "original_source_path": source["original_source_path"],
                        "original_source_name": source["original_source_name"],
                        "summary": {
                            "provider": provider.provider,
                            "model": provider.model,
                            "label": provider.label,
                            "job_id": "",
                            "status": "failed",
                            "total_elapsed_seconds": 0.0,
                            "step_runs": [],
                            "stage_scores": [],
                            "overall_score": 0.0,
                            "subtitle_count": 0,
                            "transcript_segment_count": 0,
                            "correction_count": 0,
                            "keep_ratio": 0.0,
                            "issue_codes": [f"{type(exc).__name__}: {exc}"],
                            "content_profile": {},
                            "packaging_excerpt": {},
                            "packaging_path": None,
                        },
                    }
                )
    return sorted(results, key=lambda item: item["sample_key"])


def run_worker_subprocess(
    source: dict[str, Any],
    *,
    provider: ProviderSpec,
    workflow_template: str,
    language: str,
    output_dir: str,
    worker_dir: Path,
) -> dict[str, Any]:
    result_path = worker_dir / f"{source['sample_key']}_result.json"
    log_path = worker_dir / f"{source['sample_key']}.log"
    input_path = worker_dir / f"{source['sample_key']}_input.json"
    payload = {
        "source": {**source, "path": str(source["path"])},
        "provider": asdict(provider),
        "workflow_template": workflow_template,
        "language": language,
        "output_dir": output_dir,
        "result_path": str(result_path),
    }
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker-input", str(input_path)],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path.write_text(proc.stdout or "", encoding="utf-8")
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-30:])
        raise RuntimeError(f"worker exited {proc.returncode}; log={log_path}; tail={tail}")
    if not result_path.exists():
        raise RuntimeError(f"worker did not write result; log={log_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def run_worker(worker_input: Path) -> None:
    payload = json.loads(worker_input.read_text(encoding="utf-8"))
    provider = ProviderSpec(**payload["provider"])
    apply_runtime_overrides(
        {
            "llm_mode": "performance",
            "llm_routing_mode": "bundled",
            "reasoning_provider": provider.provider,
            "reasoning_model": provider.model,
        }
    )
    result_path = Path(payload["result_path"])
    try:
        result = run_one_source(
            payload["source"],
            provider=provider,
            workflow_template=str(payload["workflow_template"]),
            language=str(payload["language"]),
            output_dir=str(payload["output_dir"]),
        )
    except Exception as exc:
        result = failed_result(payload["source"], provider, exc)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": str(result_path), "status": result["summary"]["status"]}, ensure_ascii=False), flush=True)


def failed_result(source: dict[str, Any], provider: ProviderSpec, exc: BaseException) -> dict[str, Any]:
    return {
        "sample_key": source["sample_key"],
        "original_source_path": source["original_source_path"],
        "original_source_name": source["original_source_name"],
        "summary": {
            "provider": provider.provider,
            "model": provider.model,
            "label": provider.label,
            "job_id": "",
            "status": "failed",
            "total_elapsed_seconds": 0.0,
            "step_runs": [],
            "stage_scores": [],
            "overall_score": 0.0,
            "subtitle_count": 0,
            "transcript_segment_count": 0,
            "correction_count": 0,
            "keep_ratio": 0.0,
            "issue_codes": [f"{type(exc).__name__}: {exc}"],
            "content_profile": {},
            "packaging_excerpt": {},
            "packaging_path": None,
        },
    }


def run_one_source(
    source: dict[str, Any],
    *,
    provider: ProviderSpec,
    workflow_template: str,
    language: str,
    output_dir: str,
) -> dict[str, Any]:
    job_id = asyncio.run(
        create_direct_job_for_source(
            Path(source["path"]),
            source_name=str(source.get("original_source_name") or Path(source["path"]).name),
            workflow_template=workflow_template,
            language=language,
            output_dir=output_dir,
            enhancement_modes=["multi_platform_adaptation"],
        )
    )
    step_runs, status = run_job_steps(job_id)
    finalize_job(job_id, "done" if status == "done" else status)
    summary = asyncio.run(collect_run_summary(job_id, provider, step_runs, status))
    persist_run_artifacts(summary, source=source, provider=provider)
    return {
        "sample_key": source["sample_key"],
        "original_source_path": source["original_source_path"],
        "original_source_name": source["original_source_name"],
        "summary": asdict(summary),
    }


async def create_direct_job_for_source(
    source_path: Path,
    *,
    source_name: str,
    workflow_template: str,
    language: str,
    output_dir: str,
    enhancement_modes: list[str],
) -> str:
    """Create a local-file job when inventory creation rejects duplicate file hashes."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            source_path=str(source_path),
            source_name=source_name,
            status="pending",
            language=language,
            output_dir=output_dir,
            workflow_template=workflow_template,
            workflow_mode=str(getattr(settings, "default_job_workflow_mode", None) or "standard_edit"),
            enhancement_modes=list(enhancement_modes),
            config_profile_snapshot_json={
                "llm_mode": settings.llm_mode,
                "llm_routing_mode": settings.llm_routing_mode,
                "reasoning_provider": settings.reasoning_provider,
                "reasoning_model": settings.reasoning_model,
                "transcription_provider": settings.transcription_provider,
                "transcription_model": settings.transcription_model,
                "transcription_dialect": settings.transcription_dialect,
                "default_job_workflow_mode": str(
                    getattr(settings, "default_job_workflow_mode", None) or "standard_edit"
                ),
                "default_job_enhancement_modes": list(enhancement_modes),
            },
        )
        session.add(job)
        await session.flush()
        for step in create_job_steps(job.id):
            session.add(step)
        await session.commit()
        return str(job.id)


def run_job_steps(job_id: str) -> tuple[list[StepRun], str]:
    step_runs: list[StepRun] = []
    status = "done"
    for step_name in RUN_STEPS:
        started = time.perf_counter()
        if step_name == "summary_review":
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
        if step_name in {"ai_director", "avatar_commentary", "render", "final_review"}:
            mark_step(job_id, step_name, "skipped")
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="skipped",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=f"{step_name} skipped for renderless provider A/B.",
                )
            )
            continue
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


def persist_run_artifacts(summary, *, source: dict[str, Any], provider: ProviderSpec) -> None:
    del source, provider
    # The DB artifact and final aggregate JSON are the canonical outputs for now.
    return None


if __name__ == "__main__":
    main()
