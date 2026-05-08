from __future__ import annotations

import argparse
import gc
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile


app = FastAPI(title="Qwen3-ASR Service")
model: Any | None = None
model_id: str = ""
aligner_id: str = ""
device_map: str = "cuda:0"
loaded_seconds: float | None = None
load_count: int = 0
last_loaded_at: float | None = None
last_unloaded_at: float | None = None
last_activity_monotonic: float = time.monotonic()
idle_unload_seconds: float = 10.0
model_lock = threading.RLock()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": model_id,
        "aligner": aligner_id,
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
        return {"status": "unloaded", "model": model_id, "aligner": aligner_id, "cuda_memory": cuda_memory_stats()}


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    hotwords: str = Form(default=""),
    max_new_tokens: int = Form(default=512),
    language: str = Form(default="Chinese"),
) -> dict[str, Any]:
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        tmp_path = Path(handle.name)
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    try:
        with model_lock:
            ensure_model_loaded(max_new_tokens=max_new_tokens)
            if model is None:
                raise HTTPException(status_code=503, detail="model is not loaded")
            return run_transcription(
                tmp_path,
                hotwords=hotwords,
                max_new_tokens=max_new_tokens,
                language=normalize_language(language),
            )
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def run_transcription(path: Path, *, hotwords: str, max_new_tokens: int, language: str) -> dict[str, Any]:
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    results = model.transcribe(
        audio=str(path),
        context=str(hotwords or "").strip(),
        language=language,
        return_time_stamps=True,
    )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    mark_activity()
    first = results[0] if results else None
    text = str(getattr(first, "text", "") or "").strip()
    timestamps = normalize_timestamps(getattr(first, "time_stamps", None))
    duration = resolve_audio_duration(path, timestamps=timestamps)
    if timestamps:
        segment_start = float(timestamps[0]["start"])
        segment_end = float(timestamps[-1]["end"])
    else:
        segment_start = 0.0
        segment_end = duration
    return {
        "text": text,
        "duration": duration,
        "model": model_id,
        "aligner": aligner_id,
        "hotwords": str(hotwords or "").strip(),
        "segments": [
            {
                "start_time": round(segment_start, 3),
                "end_time": round(segment_end, 3),
                "text": text,
                "words": timestamps,
            }
        ] if text else [],
        "word_or_char_timestamps": timestamps,
        "meta_info": {
            "infer_seconds": round(elapsed, 3),
            "max_new_tokens": int(max_new_tokens or 0),
            "cuda_memory": cuda_memory_stats(),
        },
    }


def normalize_timestamps(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value[0] if value and isinstance(value[0], list) else value
    else:
        data = as_dict(value)
        raw_items = data.get("items") if isinstance(data.get("items"), list) else [value]
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        row = as_dict(raw)
        nested = row.get("items")
        if isinstance(nested, list):
            for item in nested:
                normalized = normalize_timestamp_item(item)
                if normalized:
                    items.append(normalized)
            continue
        normalized = normalize_timestamp_item(raw)
        if normalized:
            items.append(normalized)
    return items


def normalize_timestamp_item(value: Any) -> dict[str, Any] | None:
    row = as_dict(value)
    text = str(row.get("text") or row.get("word") or row.get("char") or row.get("value") or "").strip()
    if not text:
        return None
    return {
        "word": text,
        "text": text,
        "start": coerce_seconds(row.get("start_time", row.get("start"))),
        "end": coerce_seconds(row.get("end_time", row.get("end"))),
    }


def as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                dumped = method()
            except TypeError:
                try:
                    dumped = method(mode="json")
                except TypeError:
                    continue
            if isinstance(dumped, dict):
                return dict(dumped)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {"value": repr(value)}


def coerce_seconds(value: Any) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def resolve_audio_duration(path: Path, *, timestamps: list[dict[str, Any]]) -> float:
    try:
        info = sf.info(str(path))
        if info.samplerate > 0:
            return round(float(info.frames) / float(info.samplerate), 3)
    except Exception:
        pass
    return round(max((float(item.get("end") or 0.0) for item in timestamps), default=0.0), 3)


def normalize_language(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"zh", "zh-cn", "zh_cn", "chinese", "mandarin", "cn"}:
        return "Chinese"
    return str(value or "").strip() or "Chinese"


def ensure_model_loaded(*, max_new_tokens: int) -> None:
    global last_loaded_at, load_count, loaded_seconds, model
    if model is not None:
        return
    from qwen_asr import Qwen3ASRModel

    started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        model_id,
        dtype=torch.bfloat16,
        device_map=device_map,
        max_inference_batch_size=1,
        max_new_tokens=int(max_new_tokens or 512),
        forced_aligner=aligner_id,
        forced_aligner_kwargs={"dtype": torch.bfloat16, "device_map": device_map},
    )
    loaded_seconds = round(time.perf_counter() - started, 3)
    last_loaded_at = time.time()
    load_count += 1
    mark_activity()


def unload_model() -> None:
    global last_unloaded_at, model
    if model is None:
        return
    model = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    last_unloaded_at = time.time()


def mark_activity() -> None:
    global last_activity_monotonic
    last_activity_monotonic = time.monotonic()


def start_idle_unload_monitor() -> None:
    if idle_unload_seconds <= 0:
        return

    def monitor() -> None:
        while True:
            time.sleep(min(30.0, max(1.0, idle_unload_seconds / 4.0)))
            if model is None:
                continue
            idle_for = time.monotonic() - last_activity_monotonic
            if idle_for < idle_unload_seconds:
                continue
            if not model_lock.acquire(blocking=False):
                continue
            try:
                if model is not None and time.monotonic() - last_activity_monotonic >= idle_unload_seconds:
                    unload_model()
            finally:
                model_lock.release()

    thread = threading.Thread(target=monitor, name="qwen3-asr-idle-unloader", daemon=True)
    thread.start()


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
    parser.add_argument("--model-id", default=os.environ.get("QWEN3_ASR_MODEL", "Qwen/Qwen3-ASR-1.7B"))
    parser.add_argument("--aligner-id", default=os.environ.get("QWEN3_ASR_ALIGNER", "Qwen/Qwen3-ForcedAligner-0.6B"))
    parser.add_argument("--device-map", default=os.environ.get("QWEN3_ASR_DEVICE_MAP", "cuda:0"))
    parser.add_argument(
        "--idle-unload-seconds",
        type=float,
        default=float(os.environ.get("QWEN3_ASR_IDLE_UNLOAD_SECONDS", "10") or 10),
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--lazy-load", action="store_true")
    return parser.parse_args()


def main() -> None:
    global aligner_id, device_map, idle_unload_seconds, model_id
    args = parse_args()
    model_id = args.model_id
    aligner_id = args.aligner_id
    device_map = args.device_map
    idle_unload_seconds = max(0.0, float(args.idle_unload_seconds or 0.0))
    if not args.lazy_load:
        with model_lock:
            ensure_model_loaded(max_new_tokens=512)
    start_idle_unload_monitor()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
