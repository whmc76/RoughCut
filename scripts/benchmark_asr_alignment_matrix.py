from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ARTIFACT_ROOT = ROOT / "output" / "test" / "asr-alignment-matrix"
SAMPLE_ROOT = ARTIFACT_ROOT / "samples"
RESULT_ROOT = ARTIFACT_ROOT / "results"

DEFAULT_MOSS_PROMPT = "Please transcribe this audio exactly. Output only the transcript text, with no explanation."

FASTER_WHISPER_HTTP_VARIANTS: dict[str, dict[str, Any]] = {
    "faster_whisper_http": {"beam_size": "5", "best_of": "5", "hotwords": "sample", "condition_on_previous_text": "false", "vad_filter": "true"},
    "faster_whisper_beam1_hot": {"beam_size": "1", "best_of": "1", "hotwords": "sample", "condition_on_previous_text": "false", "vad_filter": "true"},
    "faster_whisper_beam1_nohot": {"beam_size": "1", "best_of": "1", "hotwords": "", "condition_on_previous_text": "false", "vad_filter": "true"},
    "faster_whisper_beam5_nohot": {"beam_size": "5", "best_of": "5", "hotwords": "", "condition_on_previous_text": "false", "vad_filter": "true"},
    "faster_whisper_beam5_context_on": {"beam_size": "5", "best_of": "5", "hotwords": "sample", "condition_on_previous_text": "true", "vad_filter": "true"},
    "faster_whisper_beam5_vad_off": {"beam_size": "5", "best_of": "5", "hotwords": "sample", "condition_on_previous_text": "false", "vad_filter": "false"},
}

FUNASR_NANO_HTTP_VARIANTS: dict[str, dict[str, Any]] = {
    "funasr_nano_http": {"language": "zh", "hotwords": "sample", "use_itn": "false"},
    "funasr_nano_auto": {"language": "auto", "hotwords": "sample", "use_itn": "false"},
    "funasr_nano_itn": {"language": "zh", "hotwords": "sample", "use_itn": "true"},
}

FUNASR_PARAFORMER_HTTP_VARIANTS: dict[str, dict[str, Any]] = {
    "funasr_paraformer_http": {"language": "zh", "hotwords": "sample", "use_itn": "false"},
    "funasr_paraformer_nohot": {"language": "zh", "hotwords": "", "use_itn": "false"},
    "funasr_paraformer_itn": {"language": "zh", "hotwords": "sample", "use_itn": "true"},
}


@dataclass
class SampleSpec:
    name: str
    source_audio: str
    start: float
    end: float
    reference_text: str
    keywords: list[str]


@dataclass
class Sample:
    name: str
    source_audio: str
    sample_audio: str
    duration_sec: float
    reference_text: str
    keywords: list[str]


@dataclass
class TimedToken:
    text: str
    start: float
    end: float


@dataclass
class ASRResult:
    candidate: str
    sample: str
    ok: bool
    duration_sec: float
    infer_seconds: float | None
    realtime_factor: float | None
    gpu_peak_used_mb: int | None
    text: str
    normalized_text: str
    text_length: int
    cer: float | None
    duplicate_noise_count: int
    native_token_count: int
    native_char_coverage: float | None
    transcript_path: str | None
    raw_path: str | None
    error: str | None


@dataclass
class AlignmentResult:
    aligner: str
    text_source: str
    sample: str
    ok: bool
    duration_sec: float
    infer_seconds: float | None
    realtime_factor: float | None
    gpu_peak_used_mb: int | None
    text_length: int
    aligned_char_count: int
    char_coverage: float | None
    monotonic_violations: int
    invalid_duration_count: int
    median_char_duration_ms: float | None
    output_path: str | None
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark ASR text sources and char-level alignment strategies.")
    parser.add_argument("--manifest-json", type=Path, default=ROOT / "output" / "test" / "asr-bench" / "roughcut_known_bad_manifest.json")
    parser.add_argument(
        "--asr-candidates",
        nargs="*",
        default=["faster_whisper_http", "funasr_nano_http", "funasr_paraformer_http", "moss_audio", "moss_audio_timestamp"],
    )
    parser.add_argument("--aligners", nargs="*", default=["native_tokens", "roughcut_even_char", "whisperx", "funasr_fa_zh", "qwen3_forced_aligner_http"])
    parser.add_argument("--faster-whisper-url", default="http://127.0.0.1:30200")
    parser.add_argument("--funasr-nano-url", default="http://127.0.0.1:30210")
    parser.add_argument("--funasr-paraformer-url", default="http://127.0.0.1:30211")
    parser.add_argument("--funasr-align-url", default="http://127.0.0.1:30212")
    parser.add_argument("--moss-url", default="http://127.0.0.1:30220")
    parser.add_argument("--moss-bnb4-url", default="http://127.0.0.1:30221")
    parser.add_argument("--moss-fp16-url", default="http://127.0.0.1:30222")
    parser.add_argument("--moss-container-audio-root", default="/bench/audio")
    parser.add_argument("--qwen-align-url", default="")
    parser.add_argument("--funasr-nano-model", default="FunAudioLLM/Fun-ASR-Nano-2512")
    parser.add_argument("--funasr-paraformer-model", default="damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
    parser.add_argument("--funasr-aligner-model", default="fa-zh")
    parser.add_argument("--timeout-sec", type=float, default=1800.0)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--skip-alignment", action="store_true")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--keep-services-loaded", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    samples = build_samples(load_manifest(args.manifest_json))
    asr_results: list[ASRResult] = []
    native_tokens: dict[tuple[str, str], list[TimedToken]] = {}

    for candidate in args.asr_candidates:
        prepare_service_candidate(candidate, samples, args)
        for sample in samples:
            result, tokens = run_asr_candidate(candidate, sample, args)
            asr_results.append(result)
            native_tokens[(candidate, sample.name)] = tokens
        finish_service_candidate(candidate, args)

    alignment_results: list[AlignmentResult] = []
    if not args.skip_alignment:
        for sample in samples:
            alignment_results.extend(run_alignment_candidates_for_text(
                aligners=args.aligners,
                sample=sample,
                text_source="reference",
                text=sample.reference_text,
                native_tokens=[],
                args=args,
            ))
            for asr_result in asr_results:
                if not asr_result.ok:
                    continue
                alignment_results.extend(run_alignment_candidates_for_text(
                    aligners=args.aligners,
                    sample=sample,
                    text_source=asr_result.candidate,
                    text=asr_result.text,
                    native_tokens=native_tokens.get((asr_result.candidate, sample.name), []),
                    args=args,
                ))

    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "manifest": str(args.manifest_json),
        "samples": [asdict(item) for item in samples],
        "asr_results": [asdict(item) for item in asr_results],
        "alignment_results": [asdict(item) for item in alignment_results],
        "summary": build_summary(asr_results, alignment_results),
    }
    output_json = args.output_json or RESULT_ROOT / f"matrix_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_json.with_suffix(".md")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"JSON: {output_json}")
    print(f"Markdown: {markdown_path}")


def load_manifest(path: Path) -> list[SampleSpec]:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON list")
    specs: list[SampleSpec] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        specs.append(SampleSpec(
            name=str(item["name"]),
            source_audio=str(item["source_audio"]),
            start=float(item.get("start", 0.0) or 0.0),
            end=float(item["end"]),
            reference_text=str(item.get("reference_text") or ""),
            keywords=[str(value) for value in (item.get("keywords") or [])],
        ))
    return specs


def build_samples(specs: list[SampleSpec]) -> list[Sample]:
    samples: list[Sample] = []
    for spec in specs:
        source = Path(spec.source_audio)
        if not source.is_absolute():
            source = (ROOT / source).resolve()
        if not source.exists():
            raise SystemExit(f"sample source missing: {source}")
        sample_audio = SAMPLE_ROOT / f"{safe_name(spec.name)}_{spec.start:.3f}_{spec.end:.3f}.wav"
        if not sample_audio.exists():
            run_subprocess([
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{spec.start:.3f}",
                "-to",
                f"{spec.end:.3f}",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(sample_audio),
            ], timeout=600)
        samples.append(Sample(
            name=spec.name,
            source_audio=str(source),
            sample_audio=str(sample_audio),
            duration_sec=probe_duration(sample_audio),
            reference_text=spec.reference_text,
            keywords=spec.keywords,
        ))
    return samples


def run_asr_candidate(candidate: str, sample: Sample, args: argparse.Namespace) -> tuple[ASRResult, list[TimedToken]]:
    started = time.perf_counter()
    transcript_path = RESULT_ROOT / f"{candidate}_{sample.name}.txt"
    raw_path = RESULT_ROOT / f"{candidate}_{sample.name}.raw.json"
    try:
        with GpuSampler() as gpu:
            text, tokens, raw = dispatch_asr(candidate, sample, args)
        elapsed = time.perf_counter() - started
        transcript_path.write_text(text, encoding="utf-8")
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        normalized = normalize_eval_text(text)
        reference = normalize_eval_text(sample.reference_text)
        return ASRResult(
            candidate=candidate,
            sample=sample.name,
            ok=True,
            duration_sec=round(sample.duration_sec, 3),
            infer_seconds=round(elapsed, 3),
            realtime_factor=round(elapsed / sample.duration_sec, 3) if sample.duration_sec > 0 else None,
            gpu_peak_used_mb=gpu.peak_used_mb,
            text=text,
            normalized_text=normalized,
            text_length=len(normalized),
            cer=round(levenshtein(reference, normalized) / len(reference), 4) if reference else None,
            duplicate_noise_count=count_duplicate_noise(text),
            native_token_count=len(tokens),
            native_char_coverage=char_coverage(text, tokens),
            transcript_path=str(transcript_path),
            raw_path=str(raw_path),
            error=None,
        ), tokens
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return ASRResult(
            candidate=candidate,
            sample=sample.name,
            ok=False,
            duration_sec=round(sample.duration_sec, 3),
            infer_seconds=round(elapsed, 3),
            realtime_factor=round(elapsed / sample.duration_sec, 3) if sample.duration_sec > 0 else None,
            gpu_peak_used_mb=None,
            text="",
            normalized_text="",
            text_length=0,
            cer=None,
            duplicate_noise_count=0,
            native_token_count=0,
            native_char_coverage=None,
            transcript_path=None,
            raw_path=None,
            error=f"{type(exc).__name__}: {exc}",
        ), []


def prepare_service_candidate(candidate: str, samples: list[Sample], args: argparse.Namespace) -> None:
    if args.keep_services_loaded:
        return
    unload_all_http_services(args)
    if args.no_warmup or not samples or not is_http_asr_candidate(candidate):
        return
    try:
        dispatch_asr(candidate, samples[0], args)
    except Exception:
        return


def finish_service_candidate(candidate: str, args: argparse.Namespace) -> None:
    if args.keep_services_loaded or not is_http_asr_candidate(candidate):
        return
    unload_http_service(asr_candidate_url(candidate, args), args.timeout_sec)


def is_http_asr_candidate(candidate: str) -> bool:
    return candidate in {
        *FASTER_WHISPER_HTTP_VARIANTS,
        *FUNASR_NANO_HTTP_VARIANTS,
        *FUNASR_PARAFORMER_HTTP_VARIANTS,
        "moss_audio",
        "moss_audio_bnb4",
        "moss_audio_fp16",
        "moss_audio_timestamp",
    }


def asr_candidate_url(candidate: str, args: argparse.Namespace) -> str:
    if candidate in FASTER_WHISPER_HTTP_VARIANTS:
        return args.faster_whisper_url
    if candidate in FUNASR_NANO_HTTP_VARIANTS:
        return args.funasr_nano_url
    if candidate in FUNASR_PARAFORMER_HTTP_VARIANTS:
        return args.funasr_paraformer_url
    if candidate in {"moss_audio", "moss_audio_timestamp"}:
        return args.moss_url
    if candidate == "moss_audio_bnb4":
        return args.moss_bnb4_url
    if candidate == "moss_audio_fp16":
        return args.moss_fp16_url
    return ""


def unload_all_http_services(args: argparse.Namespace) -> None:
    for url in {
        args.faster_whisper_url,
        args.funasr_nano_url,
        args.funasr_paraformer_url,
        args.funasr_align_url,
        args.moss_url,
        args.moss_bnb4_url,
        args.moss_fp16_url,
        args.qwen_align_url,
    }:
        unload_http_service(str(url or ""), args.timeout_sec)


def unload_http_service(base_url: str, timeout_sec: float) -> None:
    if not base_url:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(min(timeout_sec, 60.0), connect=5.0)) as client:
            client.post(f"{base_url.rstrip('/')}/unload")
    except Exception:
        return


def dispatch_asr(candidate: str, sample: Sample, args: argparse.Namespace) -> tuple[str, list[TimedToken], dict[str, Any]]:
    if candidate in FASTER_WHISPER_HTTP_VARIANTS:
        return call_asr_http(sample, args.faster_whisper_url, args.timeout_sec, data=build_http_variant_data(candidate, sample, FASTER_WHISPER_HTTP_VARIANTS))
    if candidate in FUNASR_NANO_HTTP_VARIANTS:
        return call_asr_http(sample, args.funasr_nano_url, args.timeout_sec, data=build_http_variant_data(candidate, sample, FUNASR_NANO_HTTP_VARIANTS))
    if candidate in FUNASR_PARAFORMER_HTTP_VARIANTS:
        return call_asr_http(sample, args.funasr_paraformer_url, args.timeout_sec, data=build_http_variant_data(candidate, sample, FUNASR_PARAFORMER_HTTP_VARIANTS))
    if candidate == "faster_whisper_large_v3":
        return run_faster_whisper(sample, model_size="large-v3")
    if candidate == "funasr_nano_2512":
        return run_funasr(sample, model_name=args.funasr_nano_model)
    if candidate == "funasr_paraformer_zh":
        return run_funasr(sample, model_name=args.funasr_paraformer_model)
    if candidate == "moss_audio":
        return run_moss_audio(sample, args, timestamp_mode=False)
    if candidate == "moss_audio_bnb4":
        return run_moss_audio_with_url(sample, args.moss_bnb4_url, args.timeout_sec, timestamp_mode=False)
    if candidate == "moss_audio_fp16":
        return run_moss_audio_with_url(sample, args.moss_fp16_url, args.timeout_sec, timestamp_mode=False)
    if candidate == "moss_audio_timestamp":
        return run_moss_audio(sample, args, timestamp_mode=True)
    raise ValueError(f"unknown ASR candidate: {candidate}")


def build_http_variant_data(candidate: str, sample: Sample, variants: dict[str, dict[str, Any]]) -> dict[str, Any]:
    data = dict(variants[candidate])
    if data.get("hotwords") == "sample":
        data["hotwords"] = ", ".join(sample.keywords)
    data.setdefault("language", "zh")
    return data


def run_faster_whisper(sample: Sample, *, model_size: str) -> tuple[str, list[TimedToken], dict[str, Any]]:
    from roughcut.providers.transcription.local_whisper import LocalWhisperProvider

    provider = LocalWhisperProvider(model_size=model_size)
    result = asyncio.run(provider.transcribe(Path(sample.sample_audio), language="zh-CN"))
    text = "".join(segment.text for segment in result.segments).strip()
    tokens = [
        TimedToken(text=word.word, start=float(word.start), end=float(word.end))
        for segment in result.segments
        for word in segment.words
    ]
    return text, tokens, {"provider": "faster_whisper", "model": model_size, "segments": serialize_segments(result.segments)}


def run_funasr(sample: Sample, *, model_name: str) -> tuple[str, list[TimedToken], dict[str, Any]]:
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise RuntimeError("FunASR is not installed in this environment; run uv sync --extra local-asr in an unlocked venv") from exc

    from roughcut.providers.transcription.funasr_provider import FunASRProvider

    provider = FunASRProvider(model_name=model_name)
    result = asyncio.run(provider.transcribe(Path(sample.sample_audio), language="zh-CN", prompt=", ".join(sample.keywords)))
    text = "".join(segment.text for segment in result.segments).strip()
    tokens = [
        TimedToken(text=word.word, start=float(word.start), end=float(word.end))
        for segment in result.segments
        for word in segment.words
    ]
    return text, tokens, {"provider": "funasr", "model": model_name, "segments": serialize_segments(result.segments), "automodel": repr(AutoModel)}


def call_asr_http(sample: Sample, base_url: str, timeout_sec: float, *, data: dict[str, Any] | None = None) -> tuple[str, list[TimedToken], dict[str, Any]]:
    path = Path(sample.sample_audio)
    with path.open("rb") as handle:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/transcribe",
                data=data or {},
                files={"file": (path.name, handle, "audio/wav")},
            )
    response.raise_for_status()
    payload = dict(response.json() or {})
    text = strip_reasoning(str(payload.get("text") or ""))
    return text, extract_http_timed_tokens(payload), payload


def run_moss_audio(sample: Sample, args: argparse.Namespace, *, timestamp_mode: bool) -> tuple[str, list[TimedToken], dict[str, Any]]:
    return run_moss_audio_with_url(sample, args.moss_url, args.timeout_sec, timestamp_mode=timestamp_mode)


def run_moss_audio_with_url(sample: Sample, base_url: str, timeout_sec: float, *, timestamp_mode: bool) -> tuple[str, list[TimedToken], dict[str, Any]]:
    return call_asr_http(
        sample,
        base_url,
        timeout_sec,
        data={
            "hotwords": ", ".join(sample.keywords),
            "max_new_tokens": "4096" if timestamp_mode else "2048",
            "timestamp_mode": "true" if timestamp_mode else "false",
        },
    )


def run_alignment_candidates_for_text(
    *,
    aligners: list[str],
    sample: Sample,
    text_source: str,
    text: str,
    native_tokens: list[TimedToken],
    args: argparse.Namespace,
) -> list[AlignmentResult]:
    return [run_aligner(aligner, sample, text_source, text, native_tokens, args) for aligner in aligners]


def run_aligner(
    aligner: str,
    sample: Sample,
    text_source: str,
    text: str,
    native_tokens: list[TimedToken],
    args: argparse.Namespace,
) -> AlignmentResult:
    output_path = RESULT_ROOT / f"align_{aligner}_{text_source}_{sample.name}.json"
    started = time.perf_counter()
    try:
        prepare_aligner(aligner, sample, text, native_tokens, args)
        started = time.perf_counter()
        with GpuSampler() as gpu:
            tokens = dispatch_aligner(aligner, sample, text, native_tokens, args)
        elapsed = time.perf_counter() - started
        output_path.write_text(json.dumps([asdict(token) for token in tokens], ensure_ascii=False, indent=2), encoding="utf-8")
        return build_alignment_result(
            aligner=aligner,
            text_source=text_source,
            sample=sample,
            text=text,
            tokens=tokens,
            elapsed=elapsed,
            gpu_peak=gpu.peak_used_mb,
            output_path=output_path,
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return build_alignment_result(
            aligner=aligner,
            text_source=text_source,
            sample=sample,
            text=text,
            tokens=[],
            elapsed=elapsed,
            gpu_peak=None,
            output_path=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        finish_aligner(aligner, args)


def prepare_aligner(aligner: str, sample: Sample, text: str, native_tokens: list[TimedToken], args: argparse.Namespace) -> None:
    if args.keep_services_loaded or args.no_warmup:
        return
    if aligner != "funasr_fa_zh" or not args.funasr_align_url:
        return
    unload_all_http_services(args)
    try:
        dispatch_aligner(aligner, sample, text, native_tokens, args)
    except Exception:
        return


def finish_aligner(aligner: str, args: argparse.Namespace) -> None:
    if args.keep_services_loaded:
        return
    if aligner == "funasr_fa_zh":
        unload_http_service(args.funasr_align_url, args.timeout_sec)
    elif aligner == "qwen3_forced_aligner_http":
        unload_http_service(args.qwen_align_url, args.timeout_sec)


def dispatch_aligner(aligner: str, sample: Sample, text: str, native_tokens: list[TimedToken], args: argparse.Namespace) -> list[TimedToken]:
    if aligner == "native_tokens":
        if not native_tokens:
            raise RuntimeError("native ASR result has no timestamps")
        return expand_tokens_to_chars(native_tokens)
    if aligner == "roughcut_even_char":
        return evenly_align_chars(text, duration=sample.duration_sec)
    if aligner == "qwen3_forced_aligner_http":
        if not args.qwen_align_url:
            raise RuntimeError("no --qwen-align-url configured")
        return call_qwen_aligner_http(sample, text, args.qwen_align_url, args.timeout_sec)
    if aligner == "funasr_fa_zh":
        if not args.funasr_align_url:
            raise RuntimeError("no --funasr-align-url configured")
        return call_funasr_aligner_http(sample, text, args.funasr_align_url, args.timeout_sec)
    if aligner == "whisperx":
        try:
            import whisperx  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("WhisperX is not installed in this environment") from exc
        raise RuntimeError("WhisperX runner is not wired yet; install and add language align model configuration")
    raise ValueError(f"unknown aligner: {aligner}")


def call_qwen_aligner_http(sample: Sample, text: str, base_url: str, timeout_sec: float) -> list[TimedToken]:
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/align",
            data={"text": text},
            files={"file": (Path(sample.sample_audio).name, Path(sample.sample_audio).open("rb"), "audio/wav")},
        )
    response.raise_for_status()
    payload = response.json()
    return [
        TimedToken(text=str(item.get("text") or item.get("word") or ""), start=float(item.get("start") or 0.0), end=float(item.get("end") or 0.0))
        for item in payload.get("timestamps", [])
    ]


def call_funasr_aligner_http(sample: Sample, text: str, base_url: str, timeout_sec: float) -> list[TimedToken]:
    path = Path(sample.sample_audio)
    with path.open("rb") as handle:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/align",
                data={"text": text, "language": "zh"},
                files={"file": (path.name, handle, "audio/wav")},
            )
    response.raise_for_status()
    return extract_http_timed_tokens(dict(response.json() or {}))


def extract_http_timed_tokens(payload: dict[str, Any]) -> list[TimedToken]:
    rows: list[Any] = []
    direct = payload.get("word_or_char_timestamps") or payload.get("timestamps")
    if isinstance(direct, list):
        rows.extend(direct)
    for segment in payload.get("segments") or []:
        if isinstance(segment, dict) and isinstance(segment.get("words"), list):
            rows.extend(segment["words"])
    tokens: list[TimedToken] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("word") or item.get("char") or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start", item.get("start_time", 0.0)) or 0.0)
            end = float(item.get("end", item.get("end_time", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        tokens.append(TimedToken(text=text, start=start, end=end))
    return tokens


def build_alignment_result(
    *,
    aligner: str,
    text_source: str,
    sample: Sample,
    text: str,
    tokens: list[TimedToken],
    elapsed: float | None,
    gpu_peak: int | None,
    output_path: Path | None,
    error: str | None,
) -> AlignmentResult:
    normalized = normalize_eval_text(text)
    invalid = sum(1 for token in tokens if token.end <= token.start)
    violations = 0
    previous_start = -math.inf
    for token in tokens:
        if token.start < previous_start:
            violations += 1
        previous_start = token.start
    durations = [(token.end - token.start) * 1000 for token in tokens if token.end > token.start]
    return AlignmentResult(
        aligner=aligner,
        text_source=text_source,
        sample=sample.name,
        ok=error is None,
        duration_sec=round(sample.duration_sec, 3),
        infer_seconds=round(elapsed, 3) if elapsed is not None else None,
        realtime_factor=round(elapsed / sample.duration_sec, 3) if elapsed is not None and sample.duration_sec > 0 else None,
        gpu_peak_used_mb=gpu_peak,
        text_length=len(normalized),
        aligned_char_count=sum(len(normalize_eval_text(token.text)) for token in tokens),
        char_coverage=round(char_coverage(text, tokens) or 0.0, 4) if tokens else None,
        monotonic_violations=violations,
        invalid_duration_count=invalid,
        median_char_duration_ms=round(sorted(durations)[len(durations) // 2], 2) if durations else None,
        output_path=str(output_path) if output_path else None,
        error=error,
    )


def expand_tokens_to_chars(tokens: list[TimedToken]) -> list[TimedToken]:
    chars: list[TimedToken] = []
    for token in tokens:
        units = list(normalize_eval_text(token.text))
        if not units:
            continue
        duration = max(0.001, token.end - token.start)
        for index, unit in enumerate(units):
            chars.append(TimedToken(
                text=unit,
                start=round(token.start + duration * (index / len(units)), 3),
                end=round(token.start + duration * ((index + 1) / len(units)), 3),
            ))
    return chars


def evenly_align_chars(text: str, *, duration: float) -> list[TimedToken]:
    chars = list(normalize_eval_text(text))
    if not chars:
        return []
    step = max(0.001, duration / len(chars))
    return [TimedToken(text=char, start=round(index * step, 3), end=round((index + 1) * step, 3)) for index, char in enumerate(chars)]


class GpuSampler:
    def __init__(self) -> None:
        self.peak_used_mb: int | None = None
        self._baseline_mb: int | None = None
        self._peak_absolute_mb: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> GpuSampler:
        self._baseline_mb = nvidia_smi_used_mb()
        self._peak_absolute_mb = self._baseline_mb
        self._thread = threading.Thread(target=self._poll, name="asr-benchmark-gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        after = nvidia_smi_used_mb()
        for value in (after,):
            if value is not None:
                self._peak_absolute_mb = max(self._peak_absolute_mb or value, value)
        if self._baseline_mb is None or self._peak_absolute_mb is None:
            self.peak_used_mb = None
        else:
            self.peak_used_mb = max(0, self._peak_absolute_mb - self._baseline_mb)

    def _poll(self) -> None:
        while not self._stop.wait(0.2):
            value = nvidia_smi_used_mb()
            if value is not None:
                self._peak_absolute_mb = max(self._peak_absolute_mb or value, value)


def nvidia_smi_used_mb() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    values = []
    for line in result.stdout.splitlines():
        try:
            values.append(int(line.strip()))
        except ValueError:
            pass
    return max(values) if values else None


def serialize_segments(segments: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for segment in segments:
        rows.append({
            "start": getattr(segment, "start", None),
            "end": getattr(segment, "end", None),
            "text": getattr(segment, "text", ""),
            "words": [
                {"word": getattr(word, "word", ""), "start": getattr(word, "start", None), "end": getattr(word, "end", None)}
                for word in getattr(segment, "words", [])
            ],
        })
    return rows


def char_coverage(text: str, tokens: list[TimedToken]) -> float | None:
    target = len(normalize_eval_text(text))
    if target <= 0:
        return None
    covered = sum(len(normalize_eval_text(token.text)) for token in tokens if token.end > token.start)
    return round(min(1.0, covered / target), 4)


def normalize_eval_text(value: str) -> str:
    return re.sub(r"[\s，,。.!！?？、；;：:“”\"'‘’（）()[\]【】]+", "", str(value or ""))


def count_duplicate_noise(value: str) -> int:
    compact = normalize_eval_text(value)
    return len(re.findall(r"([啊呃嗯哦哎诶呀呢嘛吧吗还就也都又再没不很太是的了个这那我你他她它给把])\1", compact))


def strip_reasoning(text: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"^\s*(transcript|transcription)\s*:\s*", "", value, flags=re.IGNORECASE).strip()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "sample")).strip("_") or "sample"


def probe_duration(path: Path) -> float:
    raw = run_subprocess(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)], timeout=120)
    data = json.loads(raw or "{}")
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def run_subprocess(cmd: list[str], *, timeout: int) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])
    return result.stdout


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        for col_index, right_char in enumerate(right, start=1):
            current.append(min(
                current[col_index - 1] + 1,
                previous[col_index] + 1,
                previous[col_index - 1] + (0 if left_char == right_char else 1),
            ))
        previous = current
    return previous[-1]


def build_summary(asr_results: list[ASRResult], alignment_results: list[AlignmentResult]) -> dict[str, Any]:
    return {
        "asr": summarize_grouped([asdict(item) for item in asr_results], "candidate", ["cer", "realtime_factor", "duplicate_noise_count", "gpu_peak_used_mb"]),
        "alignment": summarize_grouped([asdict(item) for item in alignment_results], "aligner", ["char_coverage", "realtime_factor", "monotonic_violations", "gpu_peak_used_mb"]),
    }


def summarize_grouped(rows: list[dict[str, Any]], key: str, metrics: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key)), []).append(row)
    summary = []
    for name, items in grouped.items():
        ok_items = [item for item in items if item.get("ok")]
        entry: dict[str, Any] = {"name": name, "ok": len(ok_items), "failed": len(items) - len(ok_items)}
        for metric in metrics:
            values = [float(item[metric]) for item in ok_items if item.get(metric) is not None]
            entry[f"avg_{metric}"] = round(sum(values) / len(values), 4) if values else None
        errors = [item.get("error") for item in items if item.get("error")]
        if errors:
            entry["sample_error"] = errors[0]
        summary.append(entry)
    return summary


def render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# ASR Alignment Matrix", "", f"- Created at: {payload['created_at']}", f"- Manifest: `{payload['manifest']}`", ""]
    lines.extend(["## ASR Summary", "", "| Candidate | OK | Failed | Avg CER | Avg RTF | Avg duplicate noise | Avg GPU used MB |", "|---|---:|---:|---:|---:|---:|---:|"])
    for item in payload["summary"]["asr"]:
        lines.append(f"| {item['name']} | {item['ok']} | {item['failed']} | {item.get('avg_cer')} | {item.get('avg_realtime_factor')} | {item.get('avg_duplicate_noise_count')} | {item.get('avg_gpu_peak_used_mb')} |")
    lines.extend(["", "## Alignment Summary", "", "| Aligner | OK | Failed | Avg coverage | Avg RTF | Avg violations | Avg GPU used MB |", "|---|---:|---:|---:|---:|---:|---:|"])
    for item in payload["summary"]["alignment"]:
        lines.append(f"| {item['name']} | {item['ok']} | {item['failed']} | {item.get('avg_char_coverage')} | {item.get('avg_realtime_factor')} | {item.get('avg_monotonic_violations')} | {item.get('avg_gpu_peak_used_mb')} |")
    lines.extend(["", "## Failures", ""])
    for group_name in ("asr", "alignment"):
        for item in payload["summary"][group_name]:
            if item.get("sample_error"):
                lines.append(f"- `{group_name}/{item['name']}`: {item['sample_error']}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
