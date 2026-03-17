from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ARTIFACT_ROOT = ROOT / "output" / "test" / "asr-bench"
SAMPLE_ROOT = ARTIFACT_ROOT / "samples"
RESULT_ROOT = ARTIFACT_ROOT / "results"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[dict[str, float | str]]


@dataclass
class CandidateResult:
    candidate: str
    source: str
    sample_audio: str
    init_seconds: float | None
    infer_seconds: float | None
    total_seconds: float | None
    segment_count: int
    word_count: int
    text_length: int
    punctuation_count: int
    latin_count: int
    digit_count: int
    timestamps_present: bool
    preview: str
    transcript_path: str | None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark local ASR candidates on a shared sample set.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "watch",
        help="Directory containing source videos.",
    )
    parser.add_argument(
        "--videos",
        nargs="*",
        default=[],
        help="Explicit video paths. If omitted, the shortest files in source-dir are used.",
    )
    parser.add_argument("--limit", type=int, default=3, help="How many source videos to benchmark.")
    parser.add_argument("--sample-seconds", type=int, default=60, help="Audio duration to extract from each source.")
    parser.add_argument(
        "--candidates",
        nargs="*",
        default=[
            "faster_whisper_base",
            "faster_whisper_large_v3",
            "faster_whisper_turbo",
            "funasr_paraformer_zh",
            "funasr_sensevoice_small",
            "qwen3_asr_1_7b",
            "qwen3_asr_1_7b_aligned",
        ],
        help="Candidate keys to run.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional explicit JSON output path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    sources = resolve_sources(args.source_dir, args.videos, args.limit)
    if not sources:
        raise SystemExit("No source videos found for benchmarking.")

    sample_pairs = [(source, build_audio_sample(source, args.sample_seconds)) for source in sources]

    summary: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(args.source_dir),
        "sample_seconds": args.sample_seconds,
        "sources": [str(path) for path in sources],
        "results": [],
    }

    for candidate_name in args.candidates:
        factory = CANDIDATE_FACTORIES.get(candidate_name)
        if factory is None:
            summary["results"].append(
                {
                    "candidate": candidate_name,
                    "error": f"Unknown candidate: {candidate_name}",
                }
            )
            continue
        try:
            init_seconds, runner = factory()
        except Exception as exc:
            summary["results"].append(
                {
                    "candidate": candidate_name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        first_sample = True
        for source, sample_audio in sample_pairs:
            result = benchmark_candidate(
                candidate_name,
                runner,
                source,
                sample_audio,
                init_seconds if first_sample else 0.0,
            )
            summary["results"].append(asdict(result))
            first_sample = False

    output_json = args.output_json or RESULT_ROOT / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2))
    print(f"\nFull benchmark JSON: {output_json}")


def resolve_sources(source_dir: Path, explicit: list[str], limit: int) -> list[Path]:
    if explicit:
        return [Path(item) for item in explicit]
    candidates = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and "已剪" not in path.stem
    ]
    candidates.sort(key=lambda item: (item.stat().st_size, item.name.lower()))
    return candidates[:limit]


def build_audio_sample(source: Path, sample_seconds: int) -> Path:
    sample_path = SAMPLE_ROOT / f"{source.stem}_{sample_seconds}s.wav"
    if sample_path.exists():
        return sample_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-t",
        str(sample_seconds),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(sample_path),
    ]
    run_subprocess(cmd, timeout=600)
    return sample_path


def benchmark_candidate(
    candidate_name: str,
    runner: Callable[[Path], tuple[float | None, list[TranscriptSegment], str]],
    source: Path,
    sample_audio: Path,
    init_seconds: float | None,
) -> CandidateResult:
    transcript_path = RESULT_ROOT / f"{candidate_name}_{sample_audio.stem}.txt"
    try:
        infer_seconds, segments, preview = runner(sample_audio)
        text = "".join(segment.text for segment in segments).strip()
        transcript_path.write_text(text, encoding="utf-8")
        punctuation_count = sum(1 for ch in text if ch in "，。！？；：,.!?;:")
        latin_count = sum(1 for ch in text if ch.isascii() and ch.isalpha())
        digit_count = sum(1 for ch in text if ch.isdigit())
        word_count = sum(len(segment.words) for segment in segments)
        timestamps_present = any(segment.words for segment in segments)
        return CandidateResult(
            candidate=candidate_name,
            source=str(source),
            sample_audio=str(sample_audio),
            init_seconds=round(init_seconds, 3) if init_seconds is not None else None,
            infer_seconds=round(infer_seconds, 3) if infer_seconds is not None else None,
            total_seconds=round((init_seconds or 0.0) + (infer_seconds or 0.0), 3),
            segment_count=len(segments),
            word_count=word_count,
            text_length=len(text),
            punctuation_count=punctuation_count,
            latin_count=latin_count,
            digit_count=digit_count,
            timestamps_present=timestamps_present,
            preview=preview,
            transcript_path=str(transcript_path),
        )
    except Exception as exc:
        return CandidateResult(
            candidate=candidate_name,
            source=str(source),
            sample_audio=str(sample_audio),
            init_seconds=None,
            infer_seconds=None,
            total_seconds=None,
            segment_count=0,
            word_count=0,
            text_length=0,
            punctuation_count=0,
            latin_count=0,
            digit_count=0,
            timestamps_present=False,
            preview="",
            transcript_path=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in summary["results"]:
        grouped.setdefault(item["candidate"], []).append(item)

    ranking: list[dict[str, Any]] = []
    for candidate, items in grouped.items():
        ok_items = [item for item in items if not item.get("error")]
        if not ok_items:
            ranking.append({"candidate": candidate, "status": "failed", "errors": [item.get("error") for item in items]})
            continue
        ranking.append(
            {
                "candidate": candidate,
                "status": "ok",
                "samples": len(ok_items),
                "avg_total_seconds": round(statistics.mean(item["total_seconds"] for item in ok_items), 3),
                "avg_text_length": round(statistics.mean(item["text_length"] for item in ok_items), 1),
                "timestamps_present_ratio": round(
                    statistics.mean(1.0 if item["timestamps_present"] else 0.0 for item in ok_items),
                    3,
                ),
                "sample_previews": [
                    {
                        "source": Path(item["source"]).name,
                        "preview": item["preview"],
                    }
                    for item in ok_items[:2]
                ],
            }
        )
    return {"ranking": ranking}


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
        raise RuntimeError(result.stderr[-1200:])
    return result.stdout


def runner_faster_whisper(model_size: str) -> tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]:
    from faster_whisper import WhisperModel

    device = "cuda"
    compute_type = "float16"
    load_start = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    load_elapsed = time.perf_counter() - load_start

    def run(sample_audio: Path) -> tuple[float | None, list[TranscriptSegment], str]:
        infer_start = time.perf_counter()
        raw_segments, _info = model.transcribe(
            str(sample_audio),
            language="zh",
            word_timestamps=True,
        )
        segments = []
        for segment in raw_segments:
            words = [
                {
                    "word": word.word,
                    "start": float(word.start),
                    "end": float(word.end),
                }
                for word in (segment.words or [])
            ]
            segments.append(
                TranscriptSegment(
                    start=float(segment.start),
                    end=float(segment.end),
                    text=segment.text.strip(),
                    words=words,
                )
            )
        infer_elapsed = time.perf_counter() - infer_start
        text = "".join(item.text for item in segments)
        return infer_elapsed, segments, text[:200]

    return load_elapsed, run


def runner_funasr_paraformer() -> tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]:
    from funasr import AutoModel

    load_start = time.perf_counter()
    model = AutoModel(
        model="paraformer-zh",
        hub="hf",
        disable_update=True,
        device="cuda",
    )
    load_elapsed = time.perf_counter() - load_start

    def run(sample_audio: Path) -> tuple[float | None, list[TranscriptSegment], str]:
        infer_start = time.perf_counter()
        result = model.generate(input=str(sample_audio), batch_size_s=120)
        first = result[0] if isinstance(result, list) else result
        infer_elapsed = time.perf_counter() - infer_start
        text = str(first.get("text", "")).strip()
        segments = [TranscriptSegment(start=0.0, end=probe_duration(sample_audio), text=text, words=[])]
        return infer_elapsed, segments, text[:200]

    return load_elapsed, run


def runner_funasr_sensevoice() -> tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]:
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    load_start = time.perf_counter()
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        trust_remote_code=True,
        remote_code="./model.py",
        disable_update=True,
        device="cuda:0",
    )
    load_elapsed = time.perf_counter() - load_start

    def run(sample_audio: Path) -> tuple[float | None, list[TranscriptSegment], str]:
        infer_start = time.perf_counter()
        result = model.generate(
            input=str(sample_audio),
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
        )
        first = result[0] if isinstance(result, list) else result
        infer_elapsed = time.perf_counter() - infer_start
        text = rich_transcription_postprocess(str(first.get("text", "")).strip())
        segments = [TranscriptSegment(start=0.0, end=probe_duration(sample_audio), text=text, words=[])]
        return infer_elapsed, segments, text[:200]

    return load_elapsed, run


def runner_qwen3_asr() -> tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]:
    import torch
    from qwen_asr import Qwen3ASRModel

    load_start = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        "Qwen/Qwen3-ASR-1.7B",
        device_map="cuda:0",
        dtype=torch.bfloat16,
        max_inference_batch_size=4,
    )
    load_elapsed = time.perf_counter() - load_start

    def run(sample_audio: Path) -> tuple[float | None, list[TranscriptSegment], str]:
        infer_start = time.perf_counter()
        result = model.transcribe(str(sample_audio), language="Chinese")
        infer_elapsed = time.perf_counter() - infer_start
        segments = [
            TranscriptSegment(
                start=0.0,
                end=probe_duration(sample_audio),
                text=item.text.strip(),
                words=[],
            )
            for item in result
        ]
        text = "".join(item.text for item in result).strip()
        return infer_elapsed, segments, text[:200]

    return load_elapsed, run


def runner_qwen3_asr_aligned() -> tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]:
    import torch
    from qwen_asr import Qwen3ASRModel

    load_start = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        "Qwen/Qwen3-ASR-1.7B",
        forced_aligner="Qwen/Qwen3-ForcedAligner-0.6B",
        forced_aligner_kwargs={"device_map": "cpu", "dtype": torch.float32},
        device_map="cuda:0",
        dtype=torch.bfloat16,
        max_inference_batch_size=4,
    )
    load_elapsed = time.perf_counter() - load_start

    def run(sample_audio: Path) -> tuple[float | None, list[TranscriptSegment], str]:
        infer_start = time.perf_counter()
        result = model.transcribe(str(sample_audio), language="Chinese", return_time_stamps=True)
        infer_elapsed = time.perf_counter() - infer_start
        items = list(result[0].time_stamps.items) if result and result[0].time_stamps else []
        words = [
            {
                "word": item.text,
                "start": float(item.start_time),
                "end": float(item.end_time),
            }
            for item in items
        ]
        text = "".join(item.text for item in result).strip()
        segments = [
            TranscriptSegment(
                start=float(words[0]["start"]) if words else 0.0,
                end=float(words[-1]["end"]) if words else probe_duration(sample_audio),
                text=text,
                words=words,
            )
        ]
        return infer_elapsed, segments, text[:200]

    return load_elapsed, run


def probe_duration(sample_audio: Path) -> float:
    raw = run_subprocess(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(sample_audio),
        ],
        timeout=120,
    )
    data = json.loads(raw or "{}")
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


CANDIDATE_FACTORIES: dict[
    str,
    Callable[[], tuple[float | None, Callable[[Path], tuple[float | None, list[TranscriptSegment], str]]]],
] = {
    "faster_whisper_base": lambda: runner_faster_whisper("base"),
    "faster_whisper_large_v3": lambda: runner_faster_whisper("large-v3"),
    "faster_whisper_turbo": lambda: runner_faster_whisper("turbo"),
    "funasr_paraformer_zh": runner_funasr_paraformer,
    "funasr_sensevoice_small": runner_funasr_sensevoice,
    "qwen3_asr_1_7b": runner_qwen3_asr,
    "qwen3_asr_1_7b_aligned": runner_qwen3_asr_aligned,
}


if __name__ == "__main__":
    main()
