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
from faster_whisper import WhisperModel


app = FastAPI(title="RoughCut faster-whisper ASR Service")
model: WhisperModel | None = None
model_name: str = "large-v3"
device: str = "cuda"
compute_type: str = "float16"
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
        "provider": "faster_whisper",
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
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
    beam_size: int = Form(default=5),
    best_of: int = Form(default=5),
    condition_on_previous_text: bool = Form(default=False),
    vad_filter: bool = Form(default=True),
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
            ensure_model_loaded()
            if model is None:
                raise HTTPException(status_code=503, detail="model is not loaded")
            return run_transcription(
                tmp_path,
                language=normalize_language(language),
                hotwords=hotwords,
                beam_size=max(1, int(beam_size or 1)),
                best_of=max(1, int(best_of or 1)),
                condition_on_previous_text=bool(condition_on_previous_text),
                vad_filter=bool(vad_filter),
            )
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def run_transcription(
    path: Path,
    *,
    language: str,
    hotwords: str,
    beam_size: int,
    best_of: int,
    condition_on_previous_text: bool,
    vad_filter: bool,
) -> dict[str, Any]:
    if model is None:
        raise RuntimeError("model is not loaded")
    started = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    segments_iter, info = model.transcribe(
        str(path),
        language=language,
        word_timestamps=True,
        beam_size=beam_size,
        best_of=best_of,
        condition_on_previous_text=condition_on_previous_text,
        vad_filter=vad_filter,
        initial_prompt=str(hotwords or "").strip() or None,
    )
    raw_segments = list(segments_iter)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    mark_activity()
    segments = []
    for index, segment in enumerate(raw_segments):
        words = [
            {
                "word": str(getattr(word, "word", "") or ""),
                "text": str(getattr(word, "word", "") or ""),
                "start": round(float(getattr(word, "start", 0.0) or 0.0), 3),
                "end": round(float(getattr(word, "end", 0.0) or 0.0), 3),
                "probability": getattr(word, "probability", None),
            }
            for word in (getattr(segment, "words", None) or [])
        ]
        segments.append(
            {
                "index": index,
                "start_time": round(float(segment.start), 3),
                "end_time": round(float(segment.end), 3),
                "text": str(segment.text or "").strip(),
                "words": words,
            }
        )
    text = "".join(str(item["text"]) for item in segments).strip()
    return {
        "text": text,
        "duration": resolve_audio_duration(path, fallback=float(getattr(info, "duration", 0.0) or 0.0)),
        "provider": "faster_whisper",
        "model": model_name,
        "language": language,
        "hotwords": str(hotwords or "").strip(),
        "decode_options": {
            "beam_size": beam_size,
            "best_of": best_of,
            "condition_on_previous_text": condition_on_previous_text,
            "vad_filter": vad_filter,
        },
        "segments": segments,
        "word_or_char_timestamps": [word for segment in segments for word in segment["words"]],
        "meta_info": {
            "infer_seconds": round(elapsed, 3),
            "cuda_memory": cuda_memory_stats(),
        },
    }


def ensure_model_loaded() -> None:
    global last_loaded_at, load_count, loaded_seconds, model
    if model is not None:
        return
    started = time.perf_counter()
    resolved_device = device if torch.cuda.is_available() or device == "cpu" else "cpu"
    resolved_compute = compute_type if resolved_device != "cpu" else "int8"
    model = WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute)
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


def start_idle_unload_monitor() -> None:
    if idle_unload_seconds <= 0:
        return

    def monitor() -> None:
        while True:
            time.sleep(min(30.0, max(1.0, idle_unload_seconds / 4.0)))
            if model is None:
                continue
            if time.monotonic() - last_activity_monotonic < idle_unload_seconds:
                continue
            if not model_lock.acquire(blocking=False):
                continue
            try:
                if model is not None and time.monotonic() - last_activity_monotonic >= idle_unload_seconds:
                    unload_model()
            finally:
                model_lock.release()

    threading.Thread(target=monitor, name="faster-whisper-idle-unloader", daemon=True).start()


def mark_activity() -> None:
    global last_activity_monotonic
    last_activity_monotonic = time.monotonic()


def normalize_language(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"zh-cn", "zh_cn", "chinese", "mandarin", "cn"}:
        return "zh"
    return normalized or "zh"


def resolve_audio_duration(path: Path, *, fallback: float = 0.0) -> float:
    try:
        info = sf.info(str(path))
        if info.samplerate > 0:
            return round(float(info.frames) / float(info.samplerate), 3)
    except Exception:
        pass
    return round(float(fallback or 0.0), 3)


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
    parser.add_argument("--model", default=os.environ.get("FASTER_WHISPER_MODEL", "large-v3"))
    parser.add_argument("--device", default=os.environ.get("FASTER_WHISPER_DEVICE", "cuda"))
    parser.add_argument("--compute-type", default=os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "float16"))
    parser.add_argument("--idle-unload-seconds", type=float, default=float(os.environ.get("FASTER_WHISPER_IDLE_UNLOAD_SECONDS", "900") or 900))
    parser.add_argument("--lazy-load", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=30000)
    return parser.parse_args()


def main() -> None:
    global compute_type, device, idle_unload_seconds, model_name
    args = parse_args()
    model_name = args.model
    device = args.device
    compute_type = args.compute_type
    idle_unload_seconds = max(0.0, float(args.idle_unload_seconds or 0.0))
    if not args.lazy_load:
        with model_lock:
            ensure_model_loaded()
    start_idle_unload_monitor()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
