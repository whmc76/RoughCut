from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roughcut.providers.transcription.local_http_asr import LocalHTTPASRProvider
from roughcut.speech.transcribe import (
    analyze_transcript_asr_quality,
    analyze_transcript_temporal_coverage,
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

DEFAULT_FILENAMES = [
    "矩阵 千机pro.MOV",
    "老铁匠 pei巧克力和配件.MOV",
    "IMG_0181 狐蝠工业 fxx1 星期天 戒备配色edc小副包和新款肩带.MOV",
    "maxace 蜂巢3 顶配.MOV",
    "IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
]
DEFAULT_FULL_FILENAMES = {
    "maxace 蜂巢3 顶配.MOV",
    "IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
}
HOTWORDS = (
    "NOC MT34 S06mini EDC NITECORE EDC17 EDC37 狐蝠工业 FOXBAT FXX1 "
    "HSJUN BOLTBOAT 勃朗峰户外 影蚀 maxace 蜂巢 千机pro 老铁匠 pei"
)


@dataclass
class SampleSpec:
    sample_id: str
    source: str
    window: str
    start_sec: float
    duration_sec: float
    audio_path: str


@dataclass
class CandidateMetrics:
    sample_id: str
    source: str
    window: str
    model: str
    ok: bool
    request_seconds: float | None
    real_time_factor: float | None
    duration_sec: float
    covered_end_sec: float
    trailing_gap_sec: float
    coverage_ratio: float
    segment_count: int
    word_count: int
    text_units: int
    chars_per_minute: float
    timestamps_present: bool
    duplicate_rejected: bool
    duplicate_count: int
    duplicate_affected_units: int
    temporal_rejected: bool
    keyword_hits: list[str]
    transcript_path: str | None
    raw_json_path: str | None
    preview: str
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark qwen3-asr against funasr on real EDC source videos.")
    parser.add_argument("--source-dir", type=Path, default=Path(r"data\samples"))
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / f"asr-qwen3-vs-funasr-{time.strftime('%Y%m%d-%H%M%S')}")
    parser.add_argument("--window-seconds", type=float, default=90.0)
    parser.add_argument("--skip-full", action="store_true", help="Only run head/middle/tail windows.")
    parser.add_argument("--limit", type=int, default=0, help="Limit source videos after default selection; 0 means all defaults.")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--hotwords", default=HOTWORDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_dir = args.report_dir
    sample_dir = report_dir / "audio"
    transcript_dir = report_dir / "transcripts"
    raw_dir = report_dir / "raw"
    for directory in (sample_dir, transcript_dir, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)

    sources = resolve_sources(args.source_dir, limit=args.limit)
    samples = build_samples(
        sources,
        sample_dir=sample_dir,
        window_seconds=float(args.window_seconds),
        include_full=not bool(args.skip_full),
    )
    candidates = [
        ("qwen3", "qwen3-asr-1.7b-forced-aligner", "http://127.0.0.1:30230"),
        ("funasr", "fun-asr-nano-2512", "http://127.0.0.1:30210"),
    ]

    summary: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(args.source_dir),
        "window_seconds": args.window_seconds,
        "hotwords": args.hotwords,
        "samples": [asdict(sample) for sample in samples],
        "results": [],
    }

    for candidate_key, model_name, base_url in candidates:
        print(f"\n=== {candidate_key} / {model_name} ===", flush=True)
        ensure_service_healthy(base_url)
        provider = LocalHTTPASRProvider(model_name=model_name)
        for sample in samples:
            metrics = run_candidate(
                provider=provider,
                candidate_key=candidate_key,
                model_name=model_name,
                sample=sample,
                transcript_dir=transcript_dir,
                raw_dir=raw_dir,
                language=args.language,
                hotwords=args.hotwords,
            )
            summary["results"].append(asdict(metrics))
            status = "ok" if metrics.ok else "fail"
            print(
                f"{status:4} {sample.sample_id:42} "
                f"cov={metrics.coverage_ratio:.3f} dup={metrics.duplicate_count} "
                f"rtf={metrics.real_time_factor if metrics.real_time_factor is not None else '-'} "
                f"{metrics.error or ''}",
                flush=True,
            )
        unload_service(base_url)

    report_json = report_dir / "benchmark_results.json"
    report_md = report_dir / "benchmark_report.md"
    report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(build_markdown_report(summary), encoding="utf-8")
    print(f"\nJSON: {report_json}")
    print(f"Report: {report_md}")


def resolve_sources(source_dir: Path, *, limit: int) -> list[Path]:
    by_name = {path.name: path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS}
    missing = [name for name in DEFAULT_FILENAMES if name not in by_name]
    if missing:
        raise SystemExit(f"Missing benchmark sources: {missing}")
    sources = [by_name[name] for name in DEFAULT_FILENAMES]
    return sources[:limit] if limit > 0 else sources


def build_samples(
    sources: list[Path],
    *,
    sample_dir: Path,
    window_seconds: float,
    include_full: bool,
) -> list[SampleSpec]:
    samples: list[SampleSpec] = []
    for source in sources:
        duration = probe_duration(source)
        starts: list[tuple[str, float, float]] = [("head", 0.0, min(window_seconds, duration))]
        if duration > window_seconds * 1.5:
            starts.append(("middle", max(0.0, duration / 2.0 - window_seconds / 2.0), min(window_seconds, duration)))
        if duration > window_seconds * 1.2:
            starts.append(("tail", max(0.0, duration - window_seconds), min(window_seconds, duration)))
        if include_full and source.name in DEFAULT_FULL_FILENAMES:
            starts.append(("full", 0.0, duration))
        for window, start, sample_duration in starts:
            safe_stem = safe_filename(source.stem)
            sample_id = f"{safe_stem}__{window}"
            audio_path = sample_dir / f"{sample_id}.wav"
            if not audio_path.exists() or audio_path.stat().st_size <= 0:
                export_audio_window(source, audio_path, start=start, duration=sample_duration)
            samples.append(
                SampleSpec(
                    sample_id=sample_id,
                    source=str(source),
                    window=window,
                    start_sec=round(start, 3),
                    duration_sec=round(sample_duration, 3),
                    audio_path=str(audio_path),
                )
            )
    return samples


def run_candidate(
    *,
    provider: LocalHTTPASRProvider,
    candidate_key: str,
    model_name: str,
    sample: SampleSpec,
    transcript_dir: Path,
    raw_dir: Path,
    language: str,
    hotwords: str,
) -> CandidateMetrics:
    started = time.perf_counter()
    transcript_path = transcript_dir / f"{sample.sample_id}__{candidate_key}.txt"
    raw_json_path = raw_dir / f"{sample.sample_id}__{candidate_key}.json"
    try:
        result = asyncio.run(provider.transcribe(Path(sample.audio_path), language=language, prompt=hotwords))
        request_seconds = time.perf_counter() - started
        text = "".join(str(segment.text or "") for segment in result.segments).strip()
        transcript_path.write_text(text, encoding="utf-8")
        raw_json_path.write_text(json.dumps(serialize_result(result), ensure_ascii=False, indent=2), encoding="utf-8")
        coverage = analyze_transcript_temporal_coverage(result)
        duplicates = analyze_transcript_asr_quality(result)
        covered_end = float(coverage.get("covered_end_sec") or 0.0)
        duration = float(coverage.get("duration_sec") or result.duration or sample.duration_sec or 0.0)
        word_count = sum(len(list(segment.words or [])) for segment in result.segments)
        text_units = len(re.sub(r"\s+", "", text))
        return CandidateMetrics(
            sample_id=sample.sample_id,
            source=sample.source,
            window=sample.window,
            model=model_name,
            ok=True,
            request_seconds=round(request_seconds, 3),
            real_time_factor=round(request_seconds / duration, 4) if duration > 0 else None,
            duration_sec=round(duration, 3),
            covered_end_sec=round(covered_end, 3),
            trailing_gap_sec=float(coverage.get("trailing_gap_sec") or 0.0),
            coverage_ratio=float(coverage.get("coverage_ratio") or 0.0),
            segment_count=len(result.segments),
            word_count=word_count,
            text_units=text_units,
            chars_per_minute=round(text_units / max(duration / 60.0, 0.001), 1),
            timestamps_present=word_count > 0,
            duplicate_rejected=bool(duplicates.get("rejected")),
            duplicate_count=int(duplicates.get("suspicious_duplicate_count") or 0),
            duplicate_affected_units=int(duplicates.get("affected_unit_count") or 0),
            temporal_rejected=bool(coverage.get("rejected")),
            keyword_hits=keyword_hits(text),
            transcript_path=str(transcript_path),
            raw_json_path=str(raw_json_path),
            preview=text[:220],
        )
    except Exception as exc:
        duration = max(0.0, float(sample.duration_sec or 0.0))
        return CandidateMetrics(
            sample_id=sample.sample_id,
            source=sample.source,
            window=sample.window,
            model=model_name,
            ok=False,
            request_seconds=None,
            real_time_factor=None,
            duration_sec=round(duration, 3),
            covered_end_sec=0.0,
            trailing_gap_sec=duration,
            coverage_ratio=0.0,
            segment_count=0,
            word_count=0,
            text_units=0,
            chars_per_minute=0.0,
            timestamps_present=False,
            duplicate_rejected=False,
            duplicate_count=0,
            duplicate_affected_units=0,
            temporal_rejected=True,
            keyword_hits=[],
            transcript_path=None,
            raw_json_path=None,
            preview="",
            error=f"{type(exc).__name__}: {exc}",
        )


def build_markdown_report(summary: dict[str, Any]) -> str:
    results = [item for item in summary["results"] if isinstance(item, dict)]
    by_model: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_model.setdefault(item["model"], []).append(item)

    lines = [
        "# Qwen3-ASR vs FunASR Benchmark",
        "",
        f"- Created: {summary.get('created_at')}",
        f"- Source dir: `{summary.get('source_dir')}`",
        f"- Samples: {len(summary.get('samples') or [])}",
        "- Note: no human reference transcript is used, so this report scores operational quality proxies, not CER/WER.",
        "",
        "## Aggregate",
        "",
        "| Model | OK | Fail | Avg RTF | Avg Coverage | Temporal Rejects | Duplicate Rejects | Avg Text Units/min | Timestamp Ratio | Avg Keyword Hits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, items in by_model.items():
        ok_items = [item for item in items if item.get("ok")]
        fail_count = len(items) - len(ok_items)
        avg_rtf = mean_number(item.get("real_time_factor") for item in ok_items)
        avg_cov = mean_number(item.get("coverage_ratio") for item in ok_items)
        timestamp_ratio = mean_number(1.0 if item.get("timestamps_present") else 0.0 for item in ok_items)
        avg_cpm = mean_number(item.get("chars_per_minute") for item in ok_items)
        avg_hits = mean_number(len(item.get("keyword_hits") or []) for item in ok_items)
        temporal_rejects = sum(1 for item in items if item.get("temporal_rejected"))
        duplicate_rejects = sum(1 for item in items if item.get("duplicate_rejected"))
        lines.append(
            f"| {model} | {len(ok_items)} | {fail_count} | {avg_rtf:.3f} | {avg_cov:.3f} | "
            f"{temporal_rejects} | {duplicate_rejects} | {avg_cpm:.1f} | {timestamp_ratio:.3f} | {avg_hits:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Per Sample",
            "",
            "| Sample | Window | Model | Status | RTF | Coverage | Gap(s) | Segs | Words | Dup | Keywords | Preview |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in results:
        status = "ok" if item.get("ok") else f"fail: {item.get('error')}"
        lines.append(
            "| "
            + " | ".join(
                [
                    Path(str(item.get("source") or "")).name,
                    str(item.get("window") or ""),
                    str(item.get("model") or ""),
                    escape_md(status),
                    number_cell(item.get("real_time_factor")),
                    number_cell(item.get("coverage_ratio")),
                    number_cell(item.get("trailing_gap_sec")),
                    str(item.get("segment_count") or 0),
                    str(item.get("word_count") or 0),
                    str(item.get("duplicate_count") or 0),
                    escape_md(",".join(item.get("keyword_hits") or [])),
                    escape_md(str(item.get("preview") or "")[:80]),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Initial Selection Rule", ""])
    lines.append(
        "Keep `qwen3-asr` as the default unless FunASR clearly beats it on completion, temporal coverage, duplicate-noise, "
        "and manual content review. If FunASR only improves completion while producing less faithful text, it should remain "
        "a diagnostic candidate rather than an automatic replacement."
    )
    return "\n".join(lines) + "\n"


def serialize_result(result: Any) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "model": result.model,
        "duration": result.duration,
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "raw_text": segment.raw_text,
                "words": [
                    {
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "raw_text": word.raw_text,
                    }
                    for word in list(segment.words or [])
                ],
            }
            for segment in list(result.segments or [])
        ],
        "raw_payload": result.raw_payload,
    }


def ensure_service_healthy(base_url: str) -> None:
    with httpx.Client(timeout=10.0) as client:
        response = client.get(urljoin(base_url.rstrip("/") + "/", "health"))
        response.raise_for_status()


def unload_service(base_url: str) -> None:
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(urljoin(base_url.rstrip("/") + "/", "unload"))
    except Exception:
        pass


def probe_duration(path: Path) -> float:
    raw = run_subprocess(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        timeout=120,
    )
    data = json.loads(raw or "{}")
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def export_audio_window(source: Path, target: Path, *, start: float, duration: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(round(start, 3)),
        "-i",
        str(source),
        "-t",
        str(round(duration, 3)),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(target),
    ]
    run_subprocess(cmd, timeout=max(180, int(duration * 4)))


def run_subprocess(cmd: list[str], *, timeout: int) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1600:])
    return result.stdout


def keyword_hits(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text).lower()
    terms = [
        "noc",
        "mt34",
        "edc",
        "nitecore",
        "狐蝠",
        "foxbat",
        "fxx1",
        "hsjun",
        "boltboat",
        "勃朗峰",
        "影蚀",
        "maxace",
        "蜂巢",
        "千机",
        "老铁匠",
        "pei",
    ]
    return [term for term in terms if term.lower() in compact]


def mean_number(values: Any) -> float:
    numbers = [float(value) for value in values if value is not None]
    return statistics.mean(numbers) if numbers else 0.0


def number_cell(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def safe_filename(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("._")
    return text[:100] or "sample"


def escape_md(value: str) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
