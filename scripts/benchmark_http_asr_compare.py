from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "output" / "test" / "asr-bench"
SAMPLE_ROOT = ARTIFACT_ROOT / "samples"
RESULT_ROOT = ARTIFACT_ROOT / "results"

MEDIA_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DEFAULT_PROMPT = "Please transcribe this audio exactly. Output only the transcript text, with no explanation."


@dataclass
class Sample:
    source_path: str
    sample_path: str
    container_audio_path: str
    duration_sec: float
    keywords: list[str]
    reference_text: str | None


@dataclass
class Candidate:
    name: str
    kind: str
    base_url: str
    container_audio_root: str


@dataclass
class BenchmarkResult:
    candidate: str
    sample: str
    source: str
    ok: bool
    duration_sec: float
    infer_seconds: float | None
    realtime_factor: float | None
    text_length: int
    punctuation_count: int
    keyword_hits: int
    keyword_total: int
    cer: float | None
    preview: str
    transcript_path: str | None
    raw_path: str | None
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Docker-deployed ASR HTTP services on shared audio samples.")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "watch")
    parser.add_argument("--inputs", nargs="*", default=[], help="Explicit media files. Overrides --source-dir discovery.")
    parser.add_argument("--manifest-json", type=Path, default=None, help="Optional manifest with path/reference_text/keywords.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--sample-seconds", type=int, default=60)
    parser.add_argument(
        "--candidates",
        nargs="*",
        default=["current", "moss_8b_instruct", "moss_8b_thinking"],
        choices=["current", "moss_8b_instruct", "moss_8b_instruct_bnb8", "moss_8b_instruct_bnb4", "moss_8b_thinking"],
    )
    parser.add_argument("--current-url", default="http://127.0.0.1:30080")
    parser.add_argument("--moss-instruct-url", default="http://127.0.0.1:30080")
    parser.add_argument("--moss-instruct-bnb8-url", default="http://127.0.0.1:30082")
    parser.add_argument("--moss-instruct-bnb4-url", default="http://127.0.0.1:30083")
    parser.add_argument("--moss-thinking-url", default="http://127.0.0.1:30081")
    parser.add_argument("--moss-container-audio-root", default="/bench/audio")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--current-hotwords",
        choices=["filename", "none"],
        default="filename",
        help="Whether the current local HTTP ASR receives filename/manifest keywords as hotwords.",
    )
    parser.add_argument(
        "--moss-include-keywords",
        action="store_true",
        help="Append each sample's filename/manifest keywords to the MOSS transcription prompt.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--timeout-sec", type=float, default=1800.0)
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    samples = build_samples(args)
    if not samples:
        raise SystemExit("No media samples found. Pass --inputs or put media files under --source-dir.")

    candidates = build_candidates(args)
    results: list[BenchmarkResult] = []
    for candidate in candidates:
        for sample in samples:
            results.append(
                run_candidate(
                    candidate,
                    sample,
                    prompt=args.prompt,
                    max_new_tokens=args.max_new_tokens,
                    timeout_sec=args.timeout_sec,
                    current_hotwords=args.current_hotwords,
                    moss_include_keywords=args.moss_include_keywords,
                )
            )

    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    output_json = args.output_json or RESULT_ROOT / f"http_compare_{time.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "created_at": created_at,
        "sample_seconds": args.sample_seconds,
        "samples": [asdict(sample) for sample in samples],
        "results": [asdict(item) for item in results],
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_json.with_suffix(".md")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(render_console_summary(payload))
    print(f"JSON: {output_json}")
    print(f"Markdown: {markdown_path}")


def build_candidates(args: argparse.Namespace) -> list[Candidate]:
    urls = {
        "current": Candidate("current_local_http_asr", "current_local_http", args.current_url.rstrip("/"), ""),
        "moss_8b_instruct": Candidate(
            "moss_audio_8b_instruct",
            "moss_generate",
            args.moss_instruct_url.rstrip("/"),
            args.moss_container_audio_root.rstrip("/"),
        ),
        "moss_8b_instruct_bnb8": Candidate(
            "moss_audio_8b_instruct_bnb8",
            "moss_generate",
            args.moss_instruct_bnb8_url.rstrip("/"),
            args.moss_container_audio_root.rstrip("/"),
        ),
        "moss_8b_instruct_bnb4": Candidate(
            "moss_audio_8b_instruct_bnb4",
            "moss_generate",
            args.moss_instruct_bnb4_url.rstrip("/"),
            args.moss_container_audio_root.rstrip("/"),
        ),
        "moss_8b_thinking": Candidate(
            "moss_audio_8b_thinking",
            "moss_generate",
            args.moss_thinking_url.rstrip("/"),
            args.moss_container_audio_root.rstrip("/"),
        ),
    }
    return [urls[name] for name in args.candidates]


def build_samples(args: argparse.Namespace) -> list[Sample]:
    manifest = load_manifest(args.manifest_json)
    if manifest:
        items = manifest[: args.limit]
    else:
        paths = resolve_inputs(args.source_dir, args.inputs, args.limit)
        items = [{"path": str(path)} for path in paths]

    samples: list[Sample] = []
    for item in items:
        source = Path(str(item.get("path") or "")).expanduser()
        if not source.is_absolute():
            source = (ROOT / source).resolve()
        if not source.exists():
            print(f"skip missing input: {source}", file=sys.stderr)
            continue
        sample_path = build_audio_sample(source, args.sample_seconds)
        samples.append(
            Sample(
                source_path=str(source),
                sample_path=str(sample_path),
                container_audio_path=f"{args.moss_container_audio_root.rstrip('/')}/{sample_path.name}",
                duration_sec=probe_duration(sample_path),
                keywords=resolve_keywords(item, source),
                reference_text=clean_text(item.get("reference_text")),
            )
        )
    return samples


def load_manifest(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("--manifest-json must contain a JSON list")
    return [dict(item) for item in data if isinstance(item, dict)]


def resolve_inputs(source_dir: Path, explicit: list[str], limit: int) -> list[Path]:
    if explicit:
        return [Path(item) for item in explicit]
    if not source_dir.exists():
        return []
    paths = [path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS]
    paths.sort(key=lambda item: (item.stat().st_size, item.name.lower()))
    return paths[:limit]


def build_audio_sample(source: Path, sample_seconds: int) -> Path:
    safe_stem = re.sub(r"[^\w.-]+", "_", source.stem, flags=re.UNICODE).strip("_") or "sample"
    sample_path = SAMPLE_ROOT / f"{safe_stem}_{sample_seconds}s.wav"
    if sample_path.exists():
        return sample_path
    run_subprocess(
        [
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
        ],
        timeout=600,
    )
    return sample_path


def resolve_keywords(item: dict[str, Any], source: Path) -> list[str]:
    raw_keywords = item.get("keywords")
    if isinstance(raw_keywords, list):
        keywords = [clean_text(value) for value in raw_keywords]
        return [value for value in keywords if value]
    return extract_filename_keywords(source.stem)


def extract_filename_keywords(stem: str) -> list[str]:
    text = re.sub(r"[_\-]+", " ", stem)
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{1,}|[0-9][A-Za-z0-9+.-]*|[\u4e00-\u9fff]{2,}", text):
        cleaned = token.strip(".-+").lower()
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)
    return terms[:16]


def run_candidate(
    candidate: Candidate,
    sample: Sample,
    *,
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
    current_hotwords: str,
    moss_include_keywords: bool,
) -> BenchmarkResult:
    started = time.perf_counter()
    transcript_path = RESULT_ROOT / f"{candidate.name}_{Path(sample.sample_path).stem}.txt"
    raw_path = RESULT_ROOT / f"{candidate.name}_{Path(sample.sample_path).stem}.raw.json"
    try:
        if candidate.kind == "current_local_http":
            raw, text = call_current_local_http(
                candidate,
                sample,
                max_new_tokens=max_new_tokens,
                timeout_sec=timeout_sec,
                hotwords_enabled=current_hotwords == "filename",
            )
        elif candidate.kind == "moss_generate":
            raw, text = call_moss_generate(
                candidate,
                sample,
                prompt=prompt,
                max_new_tokens=max_new_tokens,
                timeout_sec=timeout_sec,
                include_keywords=moss_include_keywords,
            )
        else:
            raise ValueError(f"unsupported candidate kind: {candidate.kind}")

        elapsed = time.perf_counter() - started
        normalized_text = strip_reasoning(text).strip()
        transcript_path.write_text(normalized_text, encoding="utf-8")
        raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return build_result(
            candidate=candidate.name,
            sample=sample,
            ok=True,
            infer_seconds=elapsed,
            text=normalized_text,
            transcript_path=transcript_path,
            raw_path=raw_path,
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return build_result(
            candidate=candidate.name,
            sample=sample,
            ok=False,
            infer_seconds=elapsed,
            text="",
            transcript_path=None,
            raw_path=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def call_current_local_http(
    candidate: Candidate,
    sample: Sample,
    *,
    max_new_tokens: int,
    timeout_sec: float,
    hotwords_enabled: bool,
) -> tuple[dict[str, Any], str]:
    data = {"max_new_tokens": str(max_new_tokens)}
    if hotwords_enabled:
        data["hotwords"] = ", ".join(sample.keywords)
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
        with Path(sample.sample_path).open("rb") as handle:
            response = client.post(
                f"{candidate.base_url}/transcribe",
                files={"file": (Path(sample.sample_path).name, handle, "audio/wav")},
                data=data,
            )
    response.raise_for_status()
    raw = dict(response.json() or {})
    return raw, payload_text(raw)


def call_moss_generate(
    candidate: Candidate,
    sample: Sample,
    *,
    prompt: str,
    max_new_tokens: int,
    timeout_sec: float,
    include_keywords: bool,
) -> tuple[dict[str, Any], str]:
    request_prompt = prompt
    if include_keywords and sample.keywords:
        request_prompt = (
            f"{prompt}\n\n"
            "Pay special attention to these possible domain terms and preserve alphanumeric model names exactly: "
            f"{', '.join(sample.keywords)}."
        )
    request = {
        "text": request_prompt,
        "audio_data": sample.container_audio_path,
        "sampling_params": {
            "max_new_tokens": max_new_tokens,
            "temperature": 0.0,
        },
    }
    with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
        response = client.post(f"{candidate.base_url}/generate", json=request)
    response.raise_for_status()
    raw = dict(response.json() or {})
    return raw, str(raw.get("text") or "")


def build_result(
    *,
    candidate: str,
    sample: Sample,
    ok: bool,
    infer_seconds: float | None,
    text: str,
    transcript_path: Path | None,
    raw_path: Path | None,
    error: str | None,
) -> BenchmarkResult:
    keywords = sample.keywords
    lower_text = text.lower()
    keyword_hits = sum(1 for keyword in keywords if keyword and keyword.lower() in lower_text)
    duration = sample.duration_sec
    return BenchmarkResult(
        candidate=candidate,
        sample=Path(sample.sample_path).name,
        source=sample.source_path,
        ok=ok,
        duration_sec=round(duration, 3),
        infer_seconds=round(infer_seconds, 3) if infer_seconds is not None else None,
        realtime_factor=round((infer_seconds / duration), 3) if infer_seconds is not None and duration > 0 else None,
        text_length=len(text),
        punctuation_count=sum(1 for ch in text if ch in "，。！？；：,.!?;:"),
        keyword_hits=keyword_hits,
        keyword_total=len(keywords),
        cer=char_error_rate(sample.reference_text, text) if sample.reference_text else None,
        preview=text[:220],
        transcript_path=str(transcript_path) if transcript_path else None,
        raw_path=str(raw_path) if raw_path else None,
        error=error,
    )


def payload_text(payload: dict[str, Any]) -> str:
    text = clean_text(payload.get("text"))
    if text:
        parsed_text = segment_stream_text(text)
        return parsed_text or text
    segments = payload.get("segments")
    if isinstance(segments, list):
        return segments_text(segments)
    return ""


def segment_stream_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for candidate in segment_json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        for _ in range(2):
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    break
                continue
            break
        if isinstance(parsed, list):
            extracted = segments_text(parsed)
            if extracted:
                return extracted
        if isinstance(parsed, dict):
            extracted = segments_text([parsed])
            if extracted:
                return extracted
    return ""


def segment_json_candidates(text: str) -> list[str]:
    candidates = [text]
    if "\\\"" in text:
        candidates.append(text.replace("\\\"", "\""))
    starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if starts:
        start = min(starts)
        opener = text[start]
        closer = "]" if opener == "[" else "}"
        end = text.rfind(closer)
        if end > start:
            candidates.append(text[start : end + 1])
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def segments_text(segments: list[Any]) -> str:
    values: list[str] = []
    for segment in segments:
        if isinstance(segment, dict):
            values.append(clean_text(segment.get("text") or segment.get("Content") or segment.get("content")))
    return "".join(values).strip()


def strip_reasoning(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE)
    value = re.sub(r"^\s*(transcript|transcription)\s*:\s*", "", value, flags=re.IGNORECASE)
    return value.strip()


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def char_error_rate(reference: str | None, hypothesis: str) -> float | None:
    if not reference:
        return None
    ref = re.sub(r"\s+", "", reference)
    hyp = re.sub(r"\s+", "", hypothesis)
    if not ref:
        return None
    return round(levenshtein(ref, hyp) / len(ref), 4)


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
            insert_cost = current[col_index - 1] + 1
            delete_cost = previous[col_index] + 1
            replace_cost = previous[col_index - 1] + (0 if left_char == right_char else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def probe_duration(path: Path) -> float:
    raw = run_subprocess(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        timeout=120,
    )
    data = json.loads(raw or "{}")
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def run_subprocess(cmd: list[str], *, timeout: int) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])
    return result.stdout


def render_console_summary(payload: dict[str, Any]) -> str:
    grouped = group_results(payload["results"])
    rows: list[str] = []
    for candidate, items in grouped.items():
        ok_items = [item for item in items if item.get("ok")]
        if not ok_items:
            errors = "; ".join(str(item.get("error")) for item in items[:2])
            rows.append(f"{candidate}: failed ({errors})")
            continue
        rows.append(
            f"{candidate}: samples={len(ok_items)} "
            f"avg_rtf={mean_value(ok_items, 'realtime_factor')} "
            f"avg_len={mean_value(ok_items, 'text_length')} "
            f"keyword_hit_rate={keyword_hit_rate(ok_items)}"
        )
    return "\n".join(rows)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# ASR HTTP Benchmark",
        "",
        f"- Created at: {payload['created_at']}",
        f"- Sample seconds: {payload['sample_seconds']}",
        "",
        "## Summary",
        "",
        "| Candidate | OK samples | Avg RTF | Avg text length | Keyword hit rate | Avg CER |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate, items in group_results(payload["results"]).items():
        ok_items = [item for item in items if item.get("ok")]
        lines.append(
            "| {candidate} | {ok_count} | {rtf} | {length} | {keyword_rate} | {cer} |".format(
                candidate=candidate,
                ok_count=len(ok_items),
                rtf=mean_value(ok_items, "realtime_factor"),
                length=mean_value(ok_items, "text_length"),
                keyword_rate=keyword_hit_rate(ok_items),
                cer=mean_value([item for item in ok_items if item.get("cer") is not None], "cer"),
            )
        )
    lines.extend(["", "## Details", ""])
    for item in payload["results"]:
        lines.extend(
            [
                f"### {item['candidate']} / {item['sample']}",
                "",
                f"- OK: {item['ok']}",
                f"- RTF: {item.get('realtime_factor')}",
                f"- Keywords: {item.get('keyword_hits')}/{item.get('keyword_total')}",
                f"- CER: {item.get('cer')}",
                f"- Transcript: {item.get('transcript_path')}",
                f"- Error: {item.get('error')}",
                "",
                "```text",
                str(item.get("preview") or ""),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def group_results(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        grouped.setdefault(str(item["candidate"]), []).append(item)
    return grouped


def mean_value(items: list[dict[str, Any]], key: str) -> str:
    values = [float(item[key]) for item in items if item.get(key) is not None]
    if not values:
        return "-"
    return str(round(statistics.mean(values), 3))


def keyword_hit_rate(items: list[dict[str, Any]]) -> str:
    hit_total = sum(int(item.get("keyword_hits") or 0) for item in items)
    keyword_total = sum(int(item.get("keyword_total") or 0) for item in items)
    if keyword_total <= 0:
        return "-"
    return str(round(hit_total / keyword_total, 3))


if __name__ == "__main__":
    main()
