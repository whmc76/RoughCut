from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_text_model_comparison import (  # noqa: E402
    CODEX_MODEL,
    MINIMAX_MODEL,
    SampleInput,
    build_codex_search_prompt,
    build_samples,
    build_summary_prompt,
    build_summary_reasoning_prompt,
    build_visual_notes_prompt,
    choose_search_queries,
    resolve_video_paths,
    run_codex_json,
    run_minimax_reasoning_json,
    run_minimax_search,
    search_schema,
    summary_schema,
    temporary_settings,
)
from roughcut.providers.multimodal import complete_with_images  # noqa: E402

DEFAULT_SOURCE_ROOT = Path(r"Y:\EDC系列\未剪辑视频")
DEFAULT_REPORT_ROOT = ROOT / "output" / "test" / "visual-search-ablation"
DEFAULT_SOURCES = [
    "20260301-171443.mp4",
    "20260209-124735.mp4",
    "20260211-123939.mp4",
]


@dataclass
class VariantResult:
    summary: dict[str, Any]
    hook: dict[str, Any]
    search_results: list[dict[str, Any]]
    elapsed_seconds: float


@dataclass
class ModelAblationReport:
    text_only: VariantResult
    visual_only: VariantResult
    search_only: VariantResult
    visual_search: VariantResult


@dataclass
class SampleAblationReport:
    sample_id: str
    source_path: str
    source_name: str
    duration_seconds: float
    subtitle_count: int
    codex: ModelAblationReport
    minimax: ModelAblationReport


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a visual/search ablation benchmark for Codex GPT-5.4-mini and MiniMax M2.7-highspeed.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--sources", nargs="*", default=DEFAULT_SOURCES)
    parser.add_argument("--parallelism", type=int, default=3)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_paths = resolve_video_paths(args.source_root, explicit_sources=list(args.sources), limit=len(args.sources))
    if len(video_paths) != len(args.sources):
        raise SystemExit(f"Expected {len(args.sources)} explicit sources, resolved {len(video_paths)}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = args.report_root / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)
    samples = asyncio.run(build_samples(video_paths, report_dir=report_dir, parallelism=args.parallelism))

    reports: list[SampleAblationReport] = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.parallelism, len(samples)))) as executor:
        futures = {
            executor.submit(process_sample_sync, sample, report_dir): sample
            for sample in samples
        }
        for future in as_completed(futures):
            sample = futures[future]
            report = future.result()
            reports.append(report)
            print(json.dumps({
                "sample_id": report.sample_id,
                "source_name": report.source_name,
                "codex_text_only": report.codex.text_only.summary.get("summary", ""),
                "minimax_text_only": report.minimax.text_only.summary.get("summary", ""),
            }, ensure_ascii=False), flush=True)

    reports.sort(key=lambda item: item.sample_id)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(report_dir),
        "codex_model": CODEX_MODEL,
        "minimax_model": MINIMAX_MODEL,
        "sample_count": len(reports),
        "samples": [serialize_sample_report(item) for item in reports],
    }
    json_path = report_dir / "ablation_report.json"
    md_path = report_dir / "ablation_report.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {json_path}", flush=True)
    print(f"Markdown report: {md_path}", flush=True)


def process_sample_sync(sample: SampleInput, report_dir: Path) -> SampleAblationReport:
    print(f"[ablation] sample={sample.sample_id} source={sample.source_name}", flush=True)
    codex = run_codex_ablation(sample=sample, report_dir=report_dir)
    minimax = asyncio.run(run_minimax_ablation(sample=sample))
    return SampleAblationReport(
        sample_id=sample.sample_id,
        source_path=sample.source_path,
        source_name=sample.source_name,
        duration_seconds=sample.duration_seconds,
        subtitle_count=sample.subtitle_count,
        codex=codex,
        minimax=minimax,
    )


def build_summary_refine_prompt(sample: SampleInput, seed_summary: dict[str, Any], search_results: list[dict[str, Any]]) -> str:
    return (
        "你在做短视频文本理解校正。"
        "请基于已有摘要、字幕摘录和搜索证据，输出一份更稳妥的 JSON 摘要。"
        "只有当搜索证据直接支持时，才允许补强主体名称、型号、品类或用途；否则保持保守。"
        "\n输出字段："
        '{"subject_type":"","video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[""]}'
        f"\n已有摘要：{json.dumps(seed_summary, ensure_ascii=False)}"
        f"\n字幕摘录：\n{sample.transcript_excerpt}"
        f"\n搜索证据：{json.dumps(search_results[:5], ensure_ascii=False)}"
    )


def build_hook_prompt(summary: dict[str, Any], search_results: list[dict[str, Any]]) -> str:
    return (
        "你在做短视频发布钩子文案。"
        "请根据摘要和搜索证据，输出一个 hook 和一个更偏 B站的信息型标题。"
        "不要编造无证据参数。"
        '\n输出 JSON：{"hook":"","bilibili_title":"","risk_note":""}'
        f"\n摘要：{json.dumps(summary, ensure_ascii=False)}"
        f"\n搜索证据：{json.dumps(search_results[:4], ensure_ascii=False)}"
    )


def hook_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["hook", "bilibili_title", "risk_note"],
        "additionalProperties": False,
        "properties": {
            "hook": {"type": "string"},
            "bilibili_title": {"type": "string"},
            "risk_note": {"type": "string"},
        },
    }


def run_codex_ablation(*, sample: SampleInput, report_dir: Path) -> ModelAblationReport:
    codex_dir = report_dir / "codex_ablation" / sample.sample_id
    codex_dir.mkdir(parents=True, exist_ok=True)
    return ModelAblationReport(
        text_only=run_variant_with_timing(lambda: run_codex_variant(sample=sample, output_dir=codex_dir, variant_name="text_only", use_images=False, use_search=False)),
        visual_only=run_variant_with_timing(lambda: run_codex_variant(sample=sample, output_dir=codex_dir, variant_name="visual_only", use_images=True, use_search=False)),
        search_only=run_variant_with_timing(lambda: run_codex_variant(sample=sample, output_dir=codex_dir, variant_name="search_only", use_images=False, use_search=True)),
        visual_search=run_variant_with_timing(lambda: run_codex_variant(sample=sample, output_dir=codex_dir, variant_name="visual_search", use_images=True, use_search=True)),
    )


def run_codex_variant(
    *,
    sample: SampleInput,
    output_dir: Path,
    variant_name: str,
    use_images: bool,
    use_search: bool,
) -> VariantResult:
    variant_dir = output_dir / variant_name
    variant_dir.mkdir(parents=True, exist_ok=True)
    base_summary = run_codex_json(
        prompt=build_summary_prompt(sample),
        schema=summary_schema(),
        output_dir=variant_dir,
        step_name="summary_base",
        image_paths=sample.frame_paths if use_images else None,
        use_search=False,
    )
    search_results: list[dict[str, Any]] = []
    final_summary = base_summary
    if use_search:
        queries = choose_search_queries(base_summary)
        search_payload = run_codex_json(
            prompt=build_codex_search_prompt(queries),
            schema=search_schema(),
            output_dir=variant_dir,
            step_name="search",
            use_search=True,
        )
        search_results = list(search_payload.get("results") or [])
        final_summary = run_codex_json(
            prompt=build_summary_refine_prompt(sample, base_summary, search_results),
            schema=summary_schema(),
            output_dir=variant_dir,
            step_name="summary_refined",
            image_paths=sample.frame_paths if use_images else None,
            use_search=False,
        )
    hook = run_codex_json(
        prompt=build_hook_prompt(final_summary, search_results),
        schema=hook_schema(),
        output_dir=variant_dir,
        step_name="hook",
        use_search=False,
    )
    return VariantResult(
        summary=final_summary,
        hook=hook,
        search_results=search_results,
        elapsed_seconds=0.0,
    )


async def run_minimax_ablation(*, sample: SampleInput) -> ModelAblationReport:
    with temporary_settings(
        llm_mode="performance",
        reasoning_provider="minimax",
        reasoning_model=MINIMAX_MODEL,
    ):
        text_only = await run_variant_with_timing_async(lambda: run_minimax_variant(sample=sample, use_images=False, use_search=False))
        visual_only = await run_variant_with_timing_async(lambda: run_minimax_variant(sample=sample, use_images=True, use_search=False))
        search_only = await run_variant_with_timing_async(lambda: run_minimax_variant(sample=sample, use_images=False, use_search=True))
        visual_search = await run_variant_with_timing_async(lambda: run_minimax_variant(sample=sample, use_images=True, use_search=True))
    return ModelAblationReport(
        text_only=text_only,
        visual_only=visual_only,
        search_only=search_only,
        visual_search=visual_search,
    )


async def run_minimax_variant(*, sample: SampleInput, use_images: bool, use_search: bool) -> VariantResult:
    if use_images:
        visual_notes = await complete_with_images(
            build_visual_notes_prompt(sample),
            [Path(path) for path in sample.frame_paths],
            json_mode=False,
            max_tokens=900,
        )
        base_summary = await run_minimax_reasoning_json(build_summary_reasoning_prompt(sample, visual_notes))
    else:
        base_summary = await run_minimax_reasoning_json(build_summary_prompt(sample))

    search_results: list[dict[str, Any]] = []
    final_summary = base_summary
    if use_search:
        search_results = await run_minimax_search(choose_search_queries(base_summary))
        final_summary = await run_minimax_reasoning_json(build_summary_refine_prompt(sample, base_summary, search_results))

    hook = await run_minimax_reasoning_json(build_hook_prompt(final_summary, search_results))
    return VariantResult(
        summary=final_summary,
        hook=hook,
        search_results=search_results,
        elapsed_seconds=0.0,
    )


def run_variant_with_timing(func) -> VariantResult:
    started = time.perf_counter()
    result = func()
    result.elapsed_seconds = round(time.perf_counter() - started, 3)
    return result


async def run_variant_with_timing_async(func) -> VariantResult:
    started = time.perf_counter()
    result = await func()
    result.elapsed_seconds = round(time.perf_counter() - started, 3)
    return result


def serialize_variant(result: VariantResult) -> dict[str, Any]:
    return asdict(result)


def serialize_sample_report(report: SampleAblationReport) -> dict[str, Any]:
    return {
        "sample_id": report.sample_id,
        "source_path": report.source_path,
        "source_name": report.source_name,
        "duration_seconds": report.duration_seconds,
        "subtitle_count": report.subtitle_count,
        "codex": {
            "text_only": serialize_variant(report.codex.text_only),
            "visual_only": serialize_variant(report.codex.visual_only),
            "search_only": serialize_variant(report.codex.search_only),
            "visual_search": serialize_variant(report.codex.visual_search),
        },
        "minimax": {
            "text_only": serialize_variant(report.minimax.text_only),
            "visual_only": serialize_variant(report.minimax.visual_only),
            "search_only": serialize_variant(report.minimax.search_only),
            "visual_search": serialize_variant(report.minimax.visual_search),
        },
    }


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact = []
    for item in summary["samples"]:
        compact.append(
            {
                "sample_id": item["sample_id"],
                "source_name": item["source_name"],
                "codex_text_only": item["codex"]["text_only"]["summary"].get("summary", ""),
                "codex_visual_search": item["codex"]["visual_search"]["summary"].get("summary", ""),
                "minimax_text_only": item["minimax"]["text_only"]["summary"].get("summary", ""),
                "minimax_visual_search": item["minimax"]["visual_search"]["summary"].get("summary", ""),
            }
        )
    return {"sample_count": summary["sample_count"], "samples": compact}


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Visual Search Ablation",
        "",
        f"- created_at: {summary['created_at']}",
        f"- report_dir: {summary['report_dir']}",
        f"- codex_model: {summary['codex_model']}",
        f"- minimax_model: {summary['minimax_model']}",
        "",
    ]
    for sample in summary["samples"]:
        lines.extend(
            [
                f"## {sample['sample_id']} - {sample['source_name']}",
                "",
                f"- source_path: {sample['source_path']}",
                f"- duration_seconds: {sample['duration_seconds']}",
                f"- subtitle_count: {sample['subtitle_count']}",
                "",
            ]
        )
        for model in ("codex", "minimax"):
            lines.extend([f"### {model.upper()}", ""])
            for variant in ("text_only", "visual_only", "search_only", "visual_search"):
                block = sample[model][variant]
                lines.extend(
                    [
                        f"- {variant}: {block['summary'].get('summary', '')}",
                        f"  hook: {block['hook'].get('hook', '')}",
                    ]
                )
            lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
