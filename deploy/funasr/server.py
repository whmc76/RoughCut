from __future__ import annotations

import argparse
import gc
import importlib
import os
import re
import tempfile
import threading
import time
import unicodedata
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile


app = FastAPI(title="RoughCut FunASR Service")
model: Any | None = None
model_name: str = "paraformer-zh"
mode: str = "asr"
device: str = "cuda:0"
loaded_seconds: float | None = None
last_loaded_at: float | None = None
last_unloaded_at: float | None = None
load_count: int = 0
idle_unload_seconds: float = 900.0
last_activity_monotonic: float = time.monotonic()
model_lock = threading.RLock()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": "funasr",
        "model": model_name,
        "mode": mode,
        "device": device,
        "loaded": model is not None,
        "loaded_seconds": loaded_seconds,
        "load_count": load_count,
        "idle_unload_seconds": idle_unload_seconds,
        "idle_for_seconds": round(max(0.0, time.monotonic() - last_activity_monotonic), 3),
        "last_loaded_at": last_loaded_at,
        "last_unloaded_at": last_unloaded_at,
        "cuda_memory": cuda_memory_stats(),
    }


@app.post("/unload")
def unload() -> dict[str, Any]:
    with model_lock:
        unload_model()
        return {"status": "unloaded", "model": model_name, "cuda_memory": cuda_memory_stats()}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="zh"),
    hotwords: str = Form(default=""),
    use_itn: bool = Form(default=False),
) -> dict[str, Any]:
    path = await save_upload(file)
    try:
        with model_lock:
            ensure_model_loaded()
            raw = generate_asr(path, language=normalize_language(language), hotwords=hotwords, use_itn=bool(use_itn))
            return build_transcription_payload(raw, path, hotwords=hotwords)
    finally:
        unlink_quietly(path)


@app.post("/align")
async def align(
    file: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form(default="zh"),
) -> dict[str, Any]:
    path = await save_upload(file)
    try:
        with model_lock:
            ensure_model_loaded()
            raw = generate_alignment(path, text=text, language=normalize_language(language))
            timestamps = extract_tokens_from_raw(raw, fallback_text=text)
            if not timestamps:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "FunASR returned no usable alignment timestamps",
                        "model": model_name,
                        "mode": mode,
                        "raw_keys": collect_raw_keys(raw),
                    },
                )
            mark_activity()
            return {
                "provider": "funasr",
                "model": model_name,
                "mode": mode,
                "text": text,
                "duration": resolve_audio_duration(path),
                "timestamps": timestamps,
                "word_or_char_timestamps": timestamps,
                "raw": raw,
                "meta_info": {"cuda_memory": cuda_memory_stats()},
            }
    finally:
        unlink_quietly(path)


async def save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        tmp_path = Path(handle.name)
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return tmp_path


def generate_asr(path: Path, *, language: str, hotwords: str, use_itn: bool) -> Any:
    if model is None:
        raise HTTPException(status_code=503, detail="model is not loaded")
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    kwargs: dict[str, Any] = build_generate_kwargs(language=language, use_itn=use_itn)
    terms = normalize_hotwords(hotwords)
    if terms and not is_fun_asr_nano_model():
        kwargs["hotword"] = terms
    raw = model.generate(input=str(path), **kwargs)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    mark_activity()
    return {"result": raw, "infer_seconds": round(time.perf_counter() - started, 3), "kwargs": kwargs}


def generate_alignment(path: Path, *, text: str, language: str) -> Any:
    if model is None:
        raise HTTPException(status_code=503, detail="model is not loaded")
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    errors: list[str] = []
    with ExitStack() as stack:
        text_handle = stack.enter_context(tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False))
        text_path = Path(text_handle.name)
        text_handle.write(text)
        text_handle.flush()
        stack.callback(unlink_quietly, text_path)
        calls = [
            {
                "input": (str(path), str(text_path)),
                "data_type": ("sound", "text"),
                "batch_size_s": 300,
            },
            {
                "input": (str(path), str(text_path)),
                "data_type": ("sound", "text"),
                "sentence_timestamp": True,
                "batch_size_s": 300,
            },
            {
                "input": str(path),
                "sentence_timestamp": True,
                "batch_size_s": 300,
            },
        ]
        for kwargs in calls:
            try:
                raw = model.generate(**kwargs)
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                return {"result": raw, "infer_seconds": round(time.perf_counter() - started, 3), "kwargs": redact_paths(kwargs)}
            except (TypeError, ValueError, RuntimeError) as exc:
                errors.append(str(exc))
                continue
    raise HTTPException(status_code=500, detail={"message": "FunASR align generate call failed", "errors": errors[-3:]})


def build_generate_kwargs(*, language: str, use_itn: bool) -> dict[str, Any]:
    normalized_model = model_name.lower()
    if is_fun_asr_nano_model():
        return {
            "batch_size": 1,
            "cache": {},
            "language": "auto" if language == "auto" else "zh",
            "use_itn": use_itn,
        }
    kwargs: dict[str, Any] = {
        "language": "auto" if language == "auto" else language,
        "use_itn": use_itn,
        "batch_size_s": 300,
    }
    if "paraformer" in normalized_model:
        kwargs["hotword"] = ""
    return kwargs


def redact_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_paths(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_paths(item) for item in value)
    if isinstance(value, str) and value.startswith(tempfile.gettempdir()):
        return Path(value).name
    return value


def build_transcription_payload(raw_wrapper: dict[str, Any], path: Path, *, hotwords: str) -> dict[str, Any]:
    raw = raw_wrapper.get("result")
    segments = []
    full_text_parts: list[str] = []
    for payload in extract_segment_payloads(raw):
        text = postprocess_text(str(payload.get("text") or payload.get("raw_text") or "").strip())
        if not text:
            continue
        tokens = extract_tokens_from_payload(payload, fallback_text=text)
        start, end = extract_segment_time(payload, tokens, fallback_start=segments[-1]["end_time"] if segments else 0.0)
        full_text_parts.append(text)
        segments.append(
            {
                "index": len(segments),
                "start_time": start,
                "end_time": end,
                "text": text,
                "words": tokens,
                "raw": payload,
            }
        )
    text = "".join(full_text_parts).strip()
    return {
        "text": text,
        "duration": resolve_audio_duration(path, fallback=segments[-1]["end_time"] if segments else 0.0),
        "provider": "funasr",
        "model": model_name,
        "mode": mode,
        "hotwords": normalize_hotwords(hotwords),
        "segments": segments,
        "word_or_char_timestamps": [word for segment in segments for word in segment["words"]],
        "raw": raw,
        "meta_info": {
            "infer_seconds": raw_wrapper.get("infer_seconds"),
            "cuda_memory": cuda_memory_stats(),
        },
    }


def extract_segment_payloads(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else [raw]
    payloads: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sentence_info = item.get("sentence_info")
        if isinstance(sentence_info, list) and sentence_info:
            payloads.extend(sentence for sentence in sentence_info if isinstance(sentence, dict))
        else:
            payloads.append(item)
    return payloads


def extract_tokens_from_raw(raw_wrapper: Any, *, fallback_text: str) -> list[dict[str, Any]]:
    raw = raw_wrapper.get("result") if isinstance(raw_wrapper, dict) else raw_wrapper
    tokens: list[dict[str, Any]] = []
    for payload in extract_segment_payloads(raw):
        payload_text = str(payload.get("text") or payload.get("raw_text") or fallback_text).strip()
        tokens.extend(extract_tokens_from_payload(payload, fallback_text=payload_text))
    return tokens


def extract_tokens_from_payload(payload: dict[str, Any], *, fallback_text: str) -> list[dict[str, Any]]:
    for key in ("words", "word_timestamp", "word_timestamps", "char_timestamp", "ctc_timestamps", "timestamps"):
        values = payload.get(key)
        parsed = parse_structured_timestamps(values)
        if parsed:
            return parsed

    values = payload.get("timestamp")
    pairs = extract_timing_pairs(values if isinstance(values, list) else [])
    if not pairs:
        return []
    tokens = fit_tokens_to_timings(tokenize_alignment_text(postprocess_text(fallback_text)), len(pairs))
    return [
        {"word": token, "text": token, "start": normalize_time(start), "end": normalize_time(end)}
        for token, (start, end) in zip(tokens, pairs)
        if token
    ]


def parse_structured_timestamps(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("word") or item.get("char") or item.get("token") or "").strip()
            start = item.get("start", item.get("start_time"))
            end = item.get("end", item.get("end_time"))
            if text and start is not None and end is not None:
                parsed.append({"word": text, "text": text, "start": normalize_time(start), "end": normalize_time(end)})
            continue
        numbers = flatten_numeric_values(item)
        if len(numbers) < 2:
            continue
        parsed.append({"word": "", "text": "", "start": normalize_time(numbers[0]), "end": normalize_time(numbers[-1])})
    return [item for item in parsed if item["text"]]


def extract_segment_time(payload: dict[str, Any], tokens: list[dict[str, Any]], *, fallback_start: float) -> tuple[float, float]:
    if "start" in payload or "end" in payload:
        start = normalize_time(payload.get("start", fallback_start))
        end = normalize_time(payload.get("end", start))
        return start, max(start, end)
    if tokens:
        return float(tokens[0]["start"]), float(tokens[-1]["end"])
    return fallback_start, fallback_start


def extract_timing_pairs(values: list[Any]) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for item in values:
        numbers = flatten_numeric_values(item)
        if len(numbers) >= 2:
            pairs.append((numbers[0], numbers[-1]))
    return pairs


def tokenize_alignment_text(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_\-.]*|[\u4e00-\u9fff]", normalized):
        token = str(match.group(0) or "").strip()
        if token:
            tokens.append(token)
    return tokens


def fit_tokens_to_timings(tokens: list[str], timing_count: int) -> list[str]:
    if timing_count <= 0:
        return []
    if not tokens:
        return [""] * timing_count
    if len(tokens) == timing_count:
        return tokens
    if len(tokens) < timing_count:
        return [*tokens, *([""] * (timing_count - len(tokens)))]
    grouped: list[str] = []
    remaining = list(tokens)
    slots = timing_count
    while slots > 0:
        take = max(1, round(len(remaining) / slots))
        grouped.append("".join(remaining[:take]))
        remaining = remaining[take:]
        slots -= 1
    if remaining:
        grouped[-1] += "".join(remaining)
    return grouped[:timing_count]


def flatten_numeric_values(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, (list, tuple)):
        flattened: list[float] = []
        for item in value:
            flattened.extend(flatten_numeric_values(item))
        return flattened
    return []


def normalize_time(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1000:
        number = number / 1000.0
    return round(max(0.0, number), 3)


def postprocess_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        module = importlib.import_module("funasr.utils.postprocess_utils")
        raw = str(module.rich_transcription_postprocess(raw) or raw).strip()
    except Exception:
        pass
    compact = re.sub(r"<\|[^>]+\|>", "", raw)
    compact = "".join(ch for ch in compact if unicodedata.category(ch) != "So")
    return re.sub(r"\s+", " ", compact).strip()


def normalize_hotwords(value: str | None) -> str:
    terms = [term.strip() for term in re.split(r"[,，/;\s]+", str(value or "")) if term.strip()]
    return " ".join(terms[:64])


def normalize_language(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"zh-cn", "zh_cn", "chinese", "mandarin", "cn"}:
        return "zh"
    return normalized or "zh"


def collect_raw_keys(raw: Any) -> list[str]:
    keys: set[str] = set()
    payload = raw.get("result") if isinstance(raw, dict) else raw
    for item in extract_segment_payloads(payload):
        keys.update(str(key) for key in item.keys())
    return sorted(keys)


def resolve_audio_duration(path: Path, *, fallback: float = 0.0) -> float:
    try:
        info = sf.info(str(path))
        if info.samplerate > 0:
            return round(float(info.frames) / float(info.samplerate), 3)
    except Exception:
        pass
    return round(float(fallback or 0.0), 3)


def ensure_model_loaded() -> None:
    global last_loaded_at, load_count, loaded_seconds, model
    if model is not None:
        return
    from funasr import AutoModel

    started = time.perf_counter()
    kwargs: dict[str, Any] = {
        "model": model_name,
        "hub": "ms",
        "trust_remote_code": True,
        "disable_update": True,
    }
    if mode == "asr":
        kwargs.update(build_model_kwargs())
    if device:
        kwargs["device"] = device
    try:
        model = AutoModel(**kwargs)
    except TypeError:
        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("device", None)
        try:
            model = AutoModel(**fallback_kwargs)
        except TypeError:
            fallback_kwargs.pop("hub", None)
            fallback_kwargs.pop("vad_kwargs", None)
            model = AutoModel(**fallback_kwargs)
    loaded_seconds = round(time.perf_counter() - started, 3)
    last_loaded_at = time.time()
    load_count += 1
    mark_activity()


def build_model_kwargs() -> dict[str, Any]:
    normalized_model = model_name.lower()
    if is_fun_asr_nano_model():
        remote_code = os.environ.get("FUNASR_NANO_REMOTE_CODE", "/opt/Fun-ASR/model.py")
        return {
            "remote_code": remote_code if Path(remote_code).exists() else "./model.py",
            "vad_kwargs": {"max_single_segment_time": 30000},
        }
    if "paraformer" in normalized_model:
        return {
            "vad_model": "fsmn-vad",
            "punc_model": "ct-punc",
        }
    return {"vad_model": "fsmn-vad"}


def is_fun_asr_nano_model() -> bool:
    normalized_model = model_name.lower()
    return "fun-asr-nano" in normalized_model or "fun_asr_nano" in normalized_model


def unload_model() -> None:
    global last_unloaded_at, model
    if model is None:
        return
    model = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        if hasattr(torch.cuda, "ipc_collect"):
            torch.cuda.ipc_collect()
    last_unloaded_at = time.time()


def start_idle_unload_monitor() -> None:
    if idle_unload_seconds <= 0:
        return

    def monitor() -> None:
        while True:
            time.sleep(min(30.0, max(1.0, idle_unload_seconds / 4.0)))
            if model is None or time.monotonic() - last_activity_monotonic < idle_unload_seconds:
                continue
            if not model_lock.acquire(blocking=False):
                continue
            try:
                if model is not None and time.monotonic() - last_activity_monotonic >= idle_unload_seconds:
                    unload_model()
            finally:
                model_lock.release()

    threading.Thread(target=monitor, name="funasr-idle-unloader", daemon=True).start()


def mark_activity() -> None:
    global last_activity_monotonic
    last_activity_monotonic = time.monotonic()


def unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def cuda_memory_stats() -> dict[str, Any]:
    if not torch.cuda.is_available():
        return {}
    return {
        "allocated_mb": round(torch.cuda.memory_allocated() / 1024 / 1024, 1),
        "reserved_mb": round(torch.cuda.memory_reserved() / 1024 / 1024, 1),
        "max_allocated_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
        "max_reserved_mb": round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("FUNASR_MODEL", "paraformer-zh"))
    parser.add_argument("--mode", choices=["asr", "align"], default=os.environ.get("FUNASR_MODE", "asr"))
    parser.add_argument("--device", default=os.environ.get("FUNASR_DEVICE", "cuda:0"))
    parser.add_argument("--idle-unload-seconds", type=float, default=float(os.environ.get("FUNASR_IDLE_UNLOAD_SECONDS", "900") or 900))
    parser.add_argument("--lazy-load", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=30000)
    return parser.parse_args()


def main() -> None:
    global device, idle_unload_seconds, mode, model_name
    args = parse_args()
    model_name = args.model
    mode = args.mode
    device = args.device
    idle_unload_seconds = max(0.0, float(args.idle_unload_seconds or 0.0))
    if not args.lazy_load:
        with model_lock:
            ensure_model_loaded()
    start_idle_unload_monitor()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
