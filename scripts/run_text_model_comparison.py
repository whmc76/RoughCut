from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ["TELEGRAM_REMOTE_REVIEW_ENABLED"] = "false"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roughcut.config import get_settings, _normalize_settings
from roughcut.media.audio import extract_audio
from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.providers.search.base import SearchResult
from roughcut.providers.transcription.qwen_asr_http import QwenASRHTTPProvider
from roughcut.review.content_profile import _extract_reference_frames, build_transcript_excerpt
from roughcut.speech.postprocess import normalize_display_text, split_into_subtitles

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DEFAULT_VIDEO_ROOT = ROOT / "data" / "avatar_materials" / "profiles"
REPORT_ROOT = ROOT / "output" / "test" / "model-text-compare"
CODEX_MODEL = "gpt-5.4-mini"
MINIMAX_MODEL = "MiniMax-M2.7-highspeed"


@dataclass
class SampleInput:
    sample_id: str
    source_path: str
    source_name: str
    file_hash: str
    duration_seconds: float
    transcript_excerpt: str
    subtitle_count: int
    subtitle_excerpt: str
    subtitle_excerpt_items: list[dict[str, Any]]
    frame_paths: list[str]


@dataclass
class ModelArtifacts:
    summary: dict[str, Any]
    search_results: list[dict[str, Any]]
    subtitle_review: dict[str, Any]
    packaging: dict[str, Any]
    elapsed_seconds: float


@dataclass
class SampleReport:
    sample_id: str
    source_path: str
    duration_seconds: float
    subtitle_count: int
    codex: ModelArtifacts
    minimax: ModelArtifacts


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
    parser = argparse.ArgumentParser(description="Compare text-only output quality between Codex GPT-5.4-mini and MiniMax M2.7-highspeed on three local videos.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_VIDEO_ROOT)
    parser.add_argument("--sources", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--parallelism", type=int, default=3)
    parser.add_argument("--report-root", type=Path, default=REPORT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = args.report_root / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)

    video_paths = resolve_video_paths(args.source_root, explicit_sources=list(args.sources), limit=args.limit)
    if len(video_paths) < args.limit:
        raise SystemExit(f"Only resolved {len(video_paths)} unique videos under {args.source_root}")

    samples = asyncio.run(build_samples(video_paths, report_dir=report_dir, parallelism=args.parallelism))
    reports: list[SampleReport] = []
    for sample in samples:
        print(f"[compare] sample={sample.sample_id} source={sample.source_name}", flush=True)
        codex = run_with_timing(run_codex_bundle, sample=sample, report_dir=report_dir)
        minimax = asyncio.run(run_with_timing_async(run_minimax_bundle, sample=sample))
        reports.append(
            SampleReport(
                sample_id=sample.sample_id,
                source_path=sample.source_path,
                duration_seconds=sample.duration_seconds,
                subtitle_count=sample.subtitle_count,
                codex=codex,
                minimax=minimax,
            )
        )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(report_dir),
        "codex_model": CODEX_MODEL,
        "minimax_model": MINIMAX_MODEL,
        "sample_count": len(reports),
        "samples": [serialize_report(item) for item in reports],
    }
    json_path = report_dir / "comparison_report.json"
    md_path = report_dir / "comparison_report.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {json_path}", flush=True)
    print(f"Markdown report: {md_path}", flush=True)


def select_unique_videos(source_root: Path, *, limit: int) -> list[Path]:
    candidates = sorted(
        [path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS],
        key=lambda item: (item.stat().st_size, str(item).lower()),
    )
    selected: list[Path] = []
    seen_hashes: set[str] = set()
    for path in candidates:
        file_hash = hash_file(path)
        if file_hash in seen_hashes:
            continue
        seen_hashes.add(file_hash)
        selected.append(path)
        if len(selected) >= limit:
            break
    return selected


def resolve_video_paths(source_root: Path, *, explicit_sources: list[str], limit: int) -> list[Path]:
    if explicit_sources:
        resolved: list[Path] = []
        seen_hashes: set[str] = set()
        for raw in explicit_sources:
            candidate = Path(str(raw))
            if not candidate.is_absolute():
                candidate = source_root / candidate
            candidate = candidate.resolve()
            if not candidate.exists() or not candidate.is_file():
                continue
            file_hash = hash_file(candidate)
            if file_hash in seen_hashes:
                continue
            seen_hashes.add(file_hash)
            resolved.append(candidate)
        return resolved[:limit]
    return select_unique_videos(source_root, limit=limit)


async def build_samples(video_paths: list[Path], *, report_dir: Path, parallelism: int = 3) -> list[SampleInput]:
    sample_inputs_dir = report_dir / "samples"
    sample_inputs_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, parallelism))

    async def build_one(index: int, video_path: Path) -> SampleInput:
        async with semaphore:
            sample_id = f"sample_{index:02d}"
            sample_dir = sample_inputs_dir / sample_id
            sample_dir.mkdir(parents=True, exist_ok=True)
            print(f"[prep] sample={sample_id} source={video_path.name}", flush=True)
            file_hash = await asyncio.to_thread(hash_file, video_path)
            audio_path = sample_dir / "audio.wav"
            await extract_audio(video_path, audio_path)
            transcription = QwenASRHTTPProvider()
            transcript = await transcription.transcribe(audio_path, language="zh-CN")
            subtitle_items = build_subtitle_items(transcript)
            transcript_excerpt = build_transcript_excerpt(subtitle_items)
            subtitle_excerpt_items = select_subtitle_excerpt(subtitle_items, limit=14)
            subtitle_excerpt = render_subtitle_excerpt(subtitle_excerpt_items)
            frames_dir = sample_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            frame_paths = await asyncio.to_thread(_extract_reference_frames, video_path, frames_dir, count=3)
            duration_seconds = round(float(transcript.duration or 0.0), 3)
            sample = SampleInput(
                sample_id=sample_id,
                source_path=str(video_path),
                source_name=video_path.name,
                file_hash=file_hash,
                duration_seconds=duration_seconds,
                transcript_excerpt=transcript_excerpt,
                subtitle_count=len(subtitle_items),
                subtitle_excerpt=subtitle_excerpt,
                subtitle_excerpt_items=subtitle_excerpt_items,
                frame_paths=[str(path) for path in frame_paths],
            )
            (sample_dir / "input.json").write_text(json.dumps(asdict(sample), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[prep_done] sample={sample_id} subtitles={len(subtitle_items)} duration={duration_seconds}", flush=True)
            return sample

    tasks = [asyncio.create_task(build_one(index, video_path)) for index, video_path in enumerate(video_paths, start=1)]
    samples = await asyncio.gather(*tasks)
    return list(samples)


def build_subtitle_items(transcript_result) -> list[dict[str, Any]]:
    class SegmentRow:
        def __init__(self, segment) -> None:
            self.start_time = float(segment.start)
            self.end_time = float(segment.end)
            self.text = str(segment.text or "").strip()
            self.words_json = [
                {"word": str(word.word or ""), "start": float(word.start), "end": float(word.end)}
                for word in list(segment.words or [])
                if str(word.word or "").strip()
            ]

    rows = [SegmentRow(segment) for segment in transcript_result.segments if str(segment.text or "").strip()]
    entries = split_into_subtitles(rows, max_chars=24, max_duration=4.8)
    subtitle_items: list[dict[str, Any]] = []
    for entry in entries:
        text_norm = normalize_display_text(entry.text_norm)
        subtitle_items.append(
            {
                "index": int(entry.index),
                "start_time": round(float(entry.start), 3),
                "end_time": round(float(entry.end), 3),
                "text_raw": str(entry.text_raw or "").strip(),
                "text_norm": text_norm,
                "text_final": text_norm,
            }
        )
    return subtitle_items


def select_subtitle_excerpt(subtitle_items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if len(subtitle_items) <= limit:
        return [dict(item) for item in subtitle_items]
    head = max(4, limit // 3)
    tail = max(4, limit // 3)
    middle = max(2, limit - head - tail)
    mid_start = max(head, (len(subtitle_items) // 2) - (middle // 2))
    excerpt = subtitle_items[:head] + subtitle_items[mid_start:mid_start + middle] + subtitle_items[-tail:]
    deduped: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for item in excerpt:
        index = int(item.get("index", -1))
        if index in seen_indexes:
            continue
        seen_indexes.add(index)
        deduped.append(dict(item))
    return deduped


def render_subtitle_excerpt(subtitle_items: list[dict[str, Any]]) -> str:
    lines = []
    for item in subtitle_items:
        lines.append(
            f"[{float(item.get('start_time', 0.0)):.1f}-{float(item.get('end_time', 0.0)):.1f}] "
            f"{item.get('text_final') or item.get('text_norm') or item.get('text_raw') or ''}"
        )
    return "\n".join(lines)


def build_summary_prompt(sample: SampleInput) -> str:
    return (
        "你在做短视频文本理解对比测试。"
        "请结合提供的三张参考画面和字幕摘录，输出简洁但具体的 JSON。"
        "不要编造看不见或听不见的事实。"
        "\n输出字段："
        '{"subject_type":"","video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[""]}'
        "\n要求："
        "\n1. `subject_type` 必须尽量具体。"
        "\n2. `video_theme` 要说清这条视频到底在讲什么。"
        "\n3. `summary` 控制在 60 到 120 个中文字符。"
        "\n4. `hook_line` 要像短视频封面/标题可直接使用的一句话。"
        "\n5. `engagement_question` 要自然，不要模板化。"
        "\n6. `search_queries` 返回 2 到 3 条适合继续查证主体/参数/品牌的搜索词。"
        f"\n视频源文件：{sample.source_name}"
        f"\n字幕摘录：\n{sample.transcript_excerpt}"
    )


def build_visual_notes_prompt(sample: SampleInput) -> str:
    return (
        "请只根据提供的三张视频参考画面，提炼视觉层面的客观观察。"
        "\n输出 5 到 8 条简短中文要点。"
        "\n重点关注：主体品类、外观、颜色、使用动作、场景、画面中可读文字。"
        "\n不要猜测参数，不要补全品牌型号。"
        f"\n视频源文件：{sample.source_name}"
    )


def build_summary_reasoning_prompt(sample: SampleInput, visual_notes: str) -> str:
    return (
        "你在做短视频文本理解对比测试。"
        "请结合视觉笔记和字幕摘录，输出简洁但具体的 JSON。"
        "不要编造看不见或听不见的事实。"
        "\n输出字段："
        '{"subject_type":"","video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[""]}'
        "\n要求："
        "\n1. `subject_type` 必须尽量具体。"
        "\n2. `video_theme` 要说清这条视频到底在讲什么。"
        "\n3. `summary` 控制在 60 到 120 个中文字符。"
        "\n4. `hook_line` 要像短视频封面/标题可直接使用的一句话。"
        "\n5. `engagement_question` 要自然，不要模板化。"
        "\n6. `search_queries` 返回 2 到 3 条适合继续查证主体/参数/品牌的搜索词。"
        f"\n视觉笔记：\n{visual_notes}"
        f"\n字幕摘录：\n{sample.transcript_excerpt}"
    )


def build_subtitle_prompt(sample: SampleInput, summary: dict[str, Any]) -> str:
    return (
        "你在做短视频字幕质检。"
        "给你的是基于统一 ASR 生成的字幕摘录，请只修明显问题：错字、专有名词、数字单位、断句不顺。"
        "不要改写原意，不要润色成另一种表达。"
        "\n输出 JSON："
        '{"overall_assessment":"","top_issues":[""],"revised_excerpt":[{"index":0,"original":"","revised":"","reason":""}]}'
        "\n要求："
        "\n1. `overall_assessment` 用一句中文概括整体字幕质量。"
        "\n2. `top_issues` 最多 5 条。"
        "\n3. `revised_excerpt` 只保留最值得改的行，最多 10 条；如果没问题可返回空数组。"
        f"\n视频理解摘要：{json.dumps(summary, ensure_ascii=False)}"
        f"\n字幕摘录：\n{sample.subtitle_excerpt}"
    )


def build_packaging_prompt(sample: SampleInput, summary: dict[str, Any], search_results: list[dict[str, Any]]) -> str:
    return (
        "你在做短视频平台文案包装对比测试。"
        "请基于视频摘要、字幕摘录和搜索证据，输出适合中文短视频平台的发布文案。"
        "不要编造没有证据支撑的参数。"
        "\n输出 JSON："
        "{"
        '"hook":"","bilibili":{"titles":[""],"description":"","tags":[""]},'
        '"xiaohongshu":{"titles":[""],"description":"","tags":[""]},'
        '"douyin":{"titles":[""],"description":"","tags":[""]}'
        "}"
        "\n要求："
        "\n1. 每个平台给 3 个标题。"
        "\n2. B站偏信息密度和判断，小红书偏真实分享，抖音偏结果先行。"
        "\n3. 每个平台标签给 5 到 8 个。"
        "\n4. 如果搜索证据不充分，就保守写外观、体验、场景，不写具体参数。"
        f"\n视频理解摘要：{json.dumps(summary, ensure_ascii=False)}"
        f"\n字幕摘录：\n{sample.transcript_excerpt}"
        f"\n搜索证据：{json.dumps(search_results[:5], ensure_ascii=False)}"
    )


def choose_search_queries(summary: dict[str, Any]) -> list[str]:
    queries = [str(item).strip() for item in list(summary.get("search_queries") or []) if str(item).strip()]
    if queries:
        return queries[:2]
    fallback = " ".join(
        part
        for part in [
            str(summary.get("subject_type") or "").strip(),
            str(summary.get("video_theme") or "").strip(),
        ]
        if part
    ).strip()
    return [fallback] if fallback else []


async def run_minimax_bundle(*, sample: SampleInput) -> ModelArtifacts:
    visual_prompt = build_visual_notes_prompt(sample)
    with temporary_settings(
        llm_mode="performance",
        reasoning_provider="minimax",
        reasoning_model=MINIMAX_MODEL,
    ):
        visual_notes = await complete_with_images(
            visual_prompt,
            [Path(path) for path in sample.frame_paths],
            json_mode=False,
            max_tokens=900,
        )
        summary = await run_minimax_reasoning_json(build_summary_reasoning_prompt(sample, visual_notes))
        search_results = await run_minimax_search(choose_search_queries(summary))
        subtitle_review = await run_minimax_reasoning_json(build_subtitle_prompt(sample, summary))
        packaging = await run_minimax_reasoning_json(build_packaging_prompt(sample, summary, search_results))
    return ModelArtifacts(
        summary=summary,
        search_results=search_results,
        subtitle_review=subtitle_review,
        packaging=packaging,
        elapsed_seconds=0.0,
    )


async def run_minimax_search(queries: list[str]) -> list[dict[str, Any]]:
    if not queries:
        return []
    provider = get_search_provider()
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in queries[:2]:
        for item in await provider.search(query, max_results=5):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            results.append(search_result_to_dict(item))
            if len(results) >= 5:
                return results
    return results


async def run_minimax_reasoning_json(prompt: str) -> dict[str, Any]:
    provider = get_reasoning_provider()
    response = await provider.complete(
        [
            Message(role="system", content="你是严谨的中文短视频文本策划助手，只输出 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.2,
        max_tokens=2200,
        json_mode=True,
    )
    return response.as_json()


def run_codex_bundle(*, sample: SampleInput, report_dir: Path) -> ModelArtifacts:
    codex_dir = report_dir / "codex_sessions" / sample.sample_id
    codex_dir.mkdir(parents=True, exist_ok=True)
    summary = run_codex_json(
        prompt=build_summary_prompt(sample),
        schema=summary_schema(),
        image_paths=sample.frame_paths,
        output_dir=codex_dir,
        step_name="summary",
        use_search=False,
    )
    search_results = run_codex_json(
        prompt=build_codex_search_prompt(choose_search_queries(summary)),
        schema=search_schema(),
        output_dir=codex_dir,
        step_name="search",
        use_search=True,
    ).get("results", [])
    subtitle_review = run_codex_json(
        prompt=build_subtitle_prompt(sample, summary),
        schema=subtitle_schema(),
        output_dir=codex_dir,
        step_name="subtitle_review",
        use_search=False,
    )
    packaging = run_codex_json(
        prompt=build_packaging_prompt(sample, summary, search_results),
        schema=packaging_schema(),
        output_dir=codex_dir,
        step_name="packaging",
        use_search=False,
    )
    return ModelArtifacts(
        summary=summary,
        search_results=list(search_results),
        subtitle_review=subtitle_review,
        packaging=packaging,
        elapsed_seconds=0.0,
    )


def build_codex_search_prompt(queries: list[str]) -> str:
    query_lines = "\n".join(f"- {query}" for query in queries if query)
    return (
        "搜索以下查询，并返回最多 5 条最有价值的网页结果。"
        "优先主体官网、权威电商页、品牌发布页或清晰评测页。"
        "只输出 JSON。"
        "\n查询列表：\n"
        f"{query_lines or '- 无'}"
    )


def run_codex_json(
    *,
    prompt: str,
    schema: dict[str, Any],
    output_dir: Path,
    step_name: str,
    image_paths: list[str] | None = None,
    use_search: bool = False,
) -> dict[str, Any]:
    schema_path = output_dir / f"{step_name}_schema.json"
    output_path = output_dir / f"{step_name}_output.json"
    stdout_path = output_dir / f"{step_name}_stdout.log"
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    codex_executable = resolve_codex_executable()
    cmd = [
        codex_executable,
    ]
    if use_search:
        cmd.append("--search")
    cmd.extend([
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-m",
        CODEX_MODEL,
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
    ])
    for image_path in image_paths or []:
        cmd.extend(["-i", str(image_path)])
    run_kwargs = {
        "input": prompt,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "cwd": ROOT,
        "timeout": 900,
    }
    if codex_executable.lower().endswith((".cmd", ".bat")):
        completed = subprocess.run(
            subprocess.list2cmdline(cmd),
            shell=True,
            **run_kwargs,
        )
    else:
        completed = subprocess.run(
            cmd,
            **run_kwargs,
        )
    stdout_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"codex exec failed for {step_name}: {completed.stderr.strip() or completed.stdout.strip()}")
    text = output_path.read_text(encoding="utf-8")
    return json.loads(extract_json_text(text))


def resolve_codex_executable() -> str:
    for name in ("codex.cmd", "codex", "codex.exe"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError("codex executable not found in PATH")


def search_result_to_dict(item: SearchResult) -> dict[str, Any]:
    return {
        "title": str(item.title or "").strip(),
        "url": str(item.url or "").strip(),
        "snippet": str(item.snippet or "").strip(),
    }


def summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["subject_type", "video_theme", "summary", "hook_line", "engagement_question", "search_queries"],
        "additionalProperties": False,
        "properties": {
            "subject_type": {"type": "string"},
            "video_theme": {"type": "string"},
            "summary": {"type": "string"},
            "hook_line": {"type": "string"},
            "engagement_question": {"type": "string"},
            "search_queries": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def search_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["results"],
        "additionalProperties": False,
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "url", "snippet"],
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                },
            }
        },
    }


def subtitle_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["overall_assessment", "top_issues", "revised_excerpt"],
        "additionalProperties": False,
        "properties": {
            "overall_assessment": {"type": "string"},
            "top_issues": {"type": "array", "items": {"type": "string"}},
            "revised_excerpt": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["index", "original", "revised", "reason"],
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "original": {"type": "string"},
                        "revised": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    }


def packaging_schema() -> dict[str, Any]:
    platform_schema = {
        "type": "object",
        "required": ["titles", "description", "tags"],
        "additionalProperties": False,
        "properties": {
            "titles": {"type": "array", "items": {"type": "string"}},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "required": ["hook", "bilibili", "xiaohongshu", "douyin"],
        "additionalProperties": False,
        "properties": {
            "hook": {"type": "string"},
            "bilibili": platform_schema,
            "xiaohongshu": platform_schema,
            "douyin": platform_schema,
        },
    }


def run_with_timing(func, **kwargs: Any) -> ModelArtifacts:
    started = time.perf_counter()
    result = func(**kwargs)
    result.elapsed_seconds = round(time.perf_counter() - started, 3)
    return result


async def run_with_timing_async(func, **kwargs: Any) -> ModelArtifacts:
    started = time.perf_counter()
    result = await func(**kwargs)
    result.elapsed_seconds = round(time.perf_counter() - started, 3)
    return result


def hash_file(path: Path, chunk_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def serialize_report(report: SampleReport) -> dict[str, Any]:
    return {
        "sample_id": report.sample_id,
        "source_path": report.source_path,
        "duration_seconds": report.duration_seconds,
        "subtitle_count": report.subtitle_count,
        "codex": asdict(report.codex),
        "minimax": asdict(report.minimax),
    }


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact_samples = []
    for item in summary["samples"]:
        compact_samples.append(
            {
                "sample_id": item["sample_id"],
                "subtitle_count": item["subtitle_count"],
                "codex_summary": str((item["codex"]["summary"] or {}).get("summary") or ""),
                "minimax_summary": str((item["minimax"]["summary"] or {}).get("summary") or ""),
                "codex_elapsed_seconds": item["codex"]["elapsed_seconds"],
                "minimax_elapsed_seconds": item["minimax"]["elapsed_seconds"],
            }
        )
    return {
        "sample_count": summary["sample_count"],
        "samples": compact_samples,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Text Model Comparison",
        "",
        f"- created_at: {summary['created_at']}",
        f"- report_dir: {summary['report_dir']}",
        f"- codex_model: {summary['codex_model']}",
        f"- minimax_model: {summary['minimax_model']}",
        "",
    ]
    for item in summary["samples"]:
        codex_summary = item["codex"]["summary"]
        minimax_summary = item["minimax"]["summary"]
        lines.extend(
            [
                f"## {item['sample_id']}",
                "",
                f"- source_path: {item['source_path']}",
                f"- duration_seconds: {item['duration_seconds']}",
                f"- subtitle_count: {item['subtitle_count']}",
                "",
                "### Summary",
                "",
                f"- Codex: {codex_summary.get('summary', '')}",
                f"- MiniMax: {minimax_summary.get('summary', '')}",
                "",
                "### Subtitle Review",
                "",
                f"- Codex: {item['codex']['subtitle_review'].get('overall_assessment', '')}",
                f"- MiniMax: {item['minimax']['subtitle_review'].get('overall_assessment', '')}",
                "",
                "### Packaging Hook",
                "",
                f"- Codex: {item['codex']['packaging'].get('hook', '')}",
                f"- MiniMax: {item['minimax']['packaging'].get('hook', '')}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
