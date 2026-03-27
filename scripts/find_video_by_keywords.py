from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from roughcut.providers.transcription.local_whisper import LocalWhisperProvider

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DEFAULT_KEYWORDS = [
    "luckykiss",
    "kissport",
    "益倍萃",
    "含片",
    "益生菌",
    "弹射",
    "薄荷糖",
    "口气",
    "口腔",
]


@dataclass
class MatchResult:
    source: str
    sample_audio: str
    score: int
    matched_keywords: dict[str, int]
    transcript_preview: str
    transcript_text: str
    language: str
    segment_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan shared raw videos by transcribing the opening audio and ranking keyword hits."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Video files or directories to scan.",
    )
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=DEFAULT_KEYWORDS,
        help="Keywords to score against the transcript.",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="Whisper language hint. Default: zh",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Local whisper model size. Default: base",
    )
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=30,
        help="How many opening seconds to transcribe from each video.",
    )
    parser.add_argument(
        "--clip-offset",
        type=int,
        default=0,
        help="Start offset in seconds before extracting the sample.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of videos to scan after sorting. 0 means no limit.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=1,
        help="Only keep results whose keyword score is at least this value.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "output" / "keyword-video-scan.json",
        help="Where to write the ranked JSON report.",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        default=ROOT / "output" / "keyword-video-scan",
        help="Where to persist per-video transcript artifacts.",
    )
    return parser.parse_args()


def iter_videos(paths: Iterable[str]) -> list[Path]:
    videos: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                videos.append(path)
            continue
        if not path.exists() or not path.is_dir():
            continue
        for candidate in path.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            videos.append(candidate)
    videos.sort(key=lambda item: str(item).lower())
    return videos


def build_audio_sample(
    *,
    video_path: Path,
    sample_seconds: int,
    clip_offset: int,
    sample_root: Path,
) -> Path:
    sample_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:12]
    sample_path = sample_root / f"{video_path.stem}_{digest}_{clip_offset}s_{sample_seconds}s.wav"
    if sample_path.exists():
        return sample_path

    with tempfile.TemporaryDirectory() as td:
        temp_path = Path(td) / "sample.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip_offset),
            "-t",
            str(sample_seconds),
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(temp_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        sample_path.write_bytes(temp_path.read_bytes())
    return sample_path


def score_transcript(text: str, keywords: list[str]) -> tuple[int, dict[str, int]]:
    normalized = str(text or "").lower()
    matches: dict[str, int] = {}
    score = 0
    for keyword in keywords:
        needle = str(keyword or "").strip().lower()
        if not needle:
            continue
        count = normalized.count(needle)
        if count <= 0:
            continue
        matches[keyword] = count
        score += count * max(1, len(needle))
    return score, matches


def preview_text(text: str, *, limit: int = 120) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


async def run_scan(args: argparse.Namespace) -> dict[str, object]:
    transcript_dir: Path = args.transcript_dir
    sample_root = transcript_dir / "samples"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    sample_root.mkdir(parents=True, exist_ok=True)

    videos = iter_videos(args.paths)
    if args.limit and args.limit > 0:
        videos = videos[: args.limit]

    provider = LocalWhisperProvider(model_size=str(args.model))
    ranked: list[MatchResult] = []
    scanned = 0

    for video_path in videos:
        scanned += 1
        sample_audio = build_audio_sample(
            video_path=video_path,
            sample_seconds=int(args.sample_seconds),
            clip_offset=int(args.clip_offset),
            sample_root=sample_root,
        )
        result = await provider.transcribe(sample_audio, language=str(args.language))
        transcript_text = "\n".join(str(seg.text or "").strip() for seg in result.segments if str(seg.text or "").strip())
        score, matched_keywords = score_transcript(transcript_text, list(args.keywords))
        record = MatchResult(
            source=str(video_path),
            sample_audio=str(sample_audio),
            score=score,
            matched_keywords=matched_keywords,
            transcript_preview=preview_text(transcript_text),
            transcript_text=transcript_text,
            language=str(result.language or ""),
            segment_count=len(result.segments),
        )

        safe_name = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:12]
        artifact_path = transcript_dir / f"{safe_name}.json"
        artifact_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")

        if score >= int(args.min_score):
            ranked.append(record)

    ranked.sort(key=lambda item: (-item.score, item.source.lower()))
    payload = {
        "keywords": list(args.keywords),
        "language": args.language,
        "model": args.model,
        "sample_seconds": args.sample_seconds,
        "clip_offset": args.clip_offset,
        "scanned_videos": scanned,
        "matched_videos": len(ranked),
        "results": [asdict(item) for item in ranked],
    }
    return payload


def main() -> None:
    args = parse_args()
    payload = asyncio.run(run_scan(args))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nFull report: {args.output_json}")


if __name__ == "__main__":
    main()
