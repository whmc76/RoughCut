from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from roughcut.providers.transcription.local_http_asr import LocalHTTPASRProvider
from roughcut.remix.alignment import audit_subtitle_timing_alignment, normalize_eval_text
from roughcut.remix.contracts import AsrToken, SubtitleTiming


SRT_TIME_RE = re.compile(
    r"(?P<start>\d\d:\d\d:\d\d,\d{3})\s+-->\s+(?P<end>\d\d:\d\d:\d\d,\d{3})"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit final rendered MP4 subtitle timing against Qwen3-ASR on the rendered audio.",
    )
    parser.add_argument("--batch-report", type=Path, default=None)
    parser.add_argument("--video", type=Path, action="append", default=[])
    parser.add_argument("--srt", type=Path, action="append", default=[])
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / "rendered-subtitle-asr-audit")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--max-start-drift-sec", type=float, default=0.55)
    parser.add_argument("--max-end-drift-sec", type=float, default=1.0)
    parser.add_argument("--skip-existing-asr", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    jobs = _resolve_jobs(args)
    if not jobs:
        raise SystemExit("No video/SRT pairs to audit.")
    results = asyncio.run(_audit_jobs(jobs, args=args))
    summary = {
        "job_count": len(results),
        "pass_count": sum(1 for item in results if item.get("status") == "pass"),
        "fail_count": sum(1 for item in results if item.get("status") == "fail"),
        "jobs": results,
    }
    out_json = args.report_dir / "rendered_subtitle_asr_alignment.json"
    out_md = args.report_dir / "rendered_subtitle_asr_alignment.md"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(_render_markdown(summary), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("job_count", "pass_count", "fail_count")}, ensure_ascii=False, indent=2))
    print(f"JSON report: {out_json}")
    print(f"Markdown report: {out_md}")


def _resolve_jobs(args: argparse.Namespace) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if args.batch_report is not None:
        payload = json.loads(args.batch_report.read_text(encoding="utf-8"))
        for item in payload.get("jobs") or []:
            video = Path(str(item.get("output_path") or ""))
            if not video.exists():
                continue
            srt = video.with_suffix(".srt")
            if not srt.exists():
                candidates = list(video.parent.glob("*_成片.srt"))
                srt = candidates[0] if candidates else srt
            jobs.append(
                {
                    "job_id": item.get("job_id"),
                    "source_name": item.get("source_name"),
                    "video": video,
                    "srt": srt,
                }
            )
    for index, video in enumerate(args.video):
        srt = args.srt[index] if index < len(args.srt) else video.with_suffix(".srt")
        jobs.append({"job_id": None, "source_name": video.name, "video": video, "srt": srt})
    return jobs


async def _audit_jobs(jobs: list[dict[str, Any]], *, args: argparse.Namespace) -> list[dict[str, Any]]:
    provider = LocalHTTPASRProvider()
    results: list[dict[str, Any]] = []
    for job in jobs:
        results.append(await _audit_one(job, provider=provider, args=args))
    return results


async def _audit_one(job: dict[str, Any], *, provider: LocalHTTPASRProvider, args: argparse.Namespace) -> dict[str, Any]:
    video_path = Path(job["video"])
    srt_path = Path(job["srt"])
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", video_path.stem)[:96].strip("_") or "video"
    work_dir = args.report_dir / safe_stem
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "rendered_audio.wav"
    asr_json = work_dir / "rendered_audio_qwen3_asr.json"
    _extract_audio(video_path, audio_path)

    if asr_json.exists() and args.skip_existing_asr:
        asr_payload = json.loads(asr_json.read_text(encoding="utf-8"))
        tokens = [AsrToken(**item) for item in asr_payload.get("tokens") or []]
    else:
        result = await provider.transcribe(audio_path, language=str(args.language or "zh-CN"))
        tokens = _tokens_from_transcript(result.segments)
        asr_payload = {
            "provider": result.provider,
            "model": result.model,
            "duration": result.duration,
            "segment_count": len(result.segments),
            "token_count": len(tokens),
            "text": "".join(segment.text for segment in result.segments),
            "tokens": [asdict(token) for token in tokens],
        }
        asr_json.write_text(json.dumps(asr_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    timings = _parse_srt(srt_path)
    audit = audit_subtitle_timing_alignment(
        timings,
        tokens,
        max_start_drift_sec=float(args.max_start_drift_sec),
        max_end_drift_sec=float(args.max_end_drift_sec),
    )
    event_rows = list(audit.get("events") or [])
    bad_events = [row for row in event_rows if row.get("bad_drift") or not row.get("matched")]
    compact = {
        "job_id": job.get("job_id"),
        "source_name": job.get("source_name"),
        "status": str(audit.get("status") or "fail"),
        "video_path": str(video_path),
        "srt_path": str(srt_path),
        "audio_path": str(audio_path),
        "asr_json": str(asr_json),
        "subtitle_event_count": len(timings),
        "asr_token_count": len(tokens),
        "asr_text_chars": len(normalize_eval_text(asr_payload.get("text") or "")),
        "bad_drift_count": int(audit.get("bad_drift_count") or 0),
        "unmatched_count": int(audit.get("unmatched_count") or 0),
        "max_abs_start_drift_sec": audit.get("max_abs_start_drift_sec"),
        "max_abs_end_drift_sec": audit.get("max_abs_end_drift_sec"),
        "avg_abs_start_drift_sec": audit.get("avg_abs_start_drift_sec"),
        "avg_abs_end_drift_sec": audit.get("avg_abs_end_drift_sec"),
        "bad_events_sample": bad_events[:20],
    }
    (work_dir / "alignment_audit.json").write_text(
        json.dumps({"summary": compact, "audit": audit}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return compact


def _extract_audio(video_path: Path, audio_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True)


def _tokens_from_transcript(segments: list[Any]) -> list[AsrToken]:
    tokens: list[AsrToken] = []
    for segment in segments:
        words = list(getattr(segment, "words", []) or [])
        if words:
            for word in words:
                text = str(getattr(word, "word", "") or "").strip()
                if not normalize_eval_text(text):
                    continue
                tokens.append(
                    AsrToken(
                        text=text,
                        start_sec=float(getattr(word, "start", 0.0) or 0.0),
                        end_sec=float(getattr(word, "end", getattr(word, "start", 0.0)) or 0.0),
                    )
                )
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        chars = list(normalize_eval_text(text))
        if not chars:
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = max(start + 0.001, float(getattr(segment, "end", start) or start))
        span = end - start
        for index, char in enumerate(chars):
            tokens.append(
                AsrToken(
                    text=char,
                    start_sec=start + span * index / len(chars),
                    end_sec=start + span * (index + 1) / len(chars),
                )
            )
    tokens.sort(key=lambda item: (item.start_sec, item.end_sec))
    return tokens


def _parse_srt(path: Path) -> list[SubtitleTiming]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    timings: list[SubtitleTiming] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        match = SRT_TIME_RE.search(block)
        if not match:
            continue
        lines = [line.strip() for line in block.splitlines()]
        body_lines = [line for line in lines[2:] if line and not SRT_TIME_RE.search(line)]
        body = " ".join(body_lines).strip()
        timings.append(
            SubtitleTiming(
                text=body,
                start_sec=_parse_srt_time(match.group("start")),
                end_sec=_parse_srt_time(match.group("end")),
            )
        )
    return timings


def _parse_srt_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Rendered Subtitle ASR Alignment Audit",
        "",
        f"- job_count: `{summary.get('job_count')}`",
        f"- pass_count: `{summary.get('pass_count')}`",
        f"- fail_count: `{summary.get('fail_count')}`",
        "",
        "| Source | Status | Bad drift | Unmatched | Max start drift | Max end drift |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for job in summary.get("jobs") or []:
        lines.append(
            "| {source} | {status} | {bad} | {unmatched} | {start} | {end} |".format(
                source=str(job.get("source_name") or Path(str(job.get("video_path") or "")).name),
                status=job.get("status"),
                bad=job.get("bad_drift_count"),
                unmatched=job.get("unmatched_count"),
                start=job.get("max_abs_start_drift_sec"),
                end=job.get("max_abs_end_drift_sec"),
            )
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
