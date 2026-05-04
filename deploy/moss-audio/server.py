from __future__ import annotations

import argparse
import gc
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
import soundfile as sf
from scipy.signal import resample_poly
from transformers import BitsAndBytesConfig

from src.modeling_moss_audio import MossAudioModel
from src.processing_moss_audio import MossAudioProcessor


class GenerateRequest(BaseModel):
    text: str
    audio_data: str
    sampling_params: dict[str, Any] | None = None


app = FastAPI(title="MOSS-Audio ASR Service")
model: MossAudioModel | None = None
processor: MossAudioProcessor | None = None
model_path: str = ""
quantization: str = "none"
loaded_seconds: float | None = None
idle_unload_seconds: float = 900.0
model_lock = threading.RLock()
last_activity_monotonic: float = time.monotonic()
last_loaded_at: float | None = None
last_unloaded_at: float | None = None
load_count: int = 0


@app.get("/health")
def health() -> dict[str, Any]:
    loaded = model is not None and processor is not None
    return {
        "status": "ok",
        "model": model_path,
        "quantization": quantization,
        "loaded": loaded,
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
        return {
            "status": "unloaded",
            "model": model_path,
            "cuda_memory": cuda_memory_stats(),
        }


@app.post("/generate")
def generate(request: GenerateRequest) -> dict[str, Any]:
    with model_lock:
        ensure_model_loaded()
        active_model = model
        active_processor = processor
        if active_model is None or active_processor is None:
            raise HTTPException(status_code=503, detail="model is not loaded")

        audio_path = Path(request.audio_data)
        if not audio_path.exists():
            raise HTTPException(status_code=400, detail=f"audio_data does not exist: {audio_path}")

        params = dict(request.sampling_params or {})
        max_new_tokens = int(params.get("max_new_tokens") or params.get("max_tokens") or 1024)
        temperature = float(params.get("temperature", 0.0) or 0.0)
        top_p = float(params.get("top_p", 1.0) or 1.0)
        top_k = int(params.get("top_k", 50) or 50)
        do_sample = temperature > 0.0

        started = time.perf_counter()
        raw_audio = load_audio_file(audio_path, sample_rate=active_processor.config.mel_sr)
        duration = audio_duration(raw_audio, sample_rate=active_processor.config.mel_sr)
        inputs = active_processor(text=request.text, audios=[raw_audio], return_tensors="pt")
        inputs = inputs.to(active_model.device)
        if inputs.get("audio_data") is not None:
            inputs["audio_data"] = inputs["audio_data"].to(active_model.dtype)
        inputs["audio_input_mask"] = inputs["input_ids"] == active_processor.audio_token_id

        with torch.no_grad():
            generated_ids = active_model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=do_sample,
                num_beams=1,
                temperature=max(temperature, 1e-5) if do_sample else None,
                top_p=top_p,
                top_k=top_k,
                use_cache=True,
            )

        input_len = inputs["input_ids"].shape[1]
        text = active_processor.decode(generated_ids[0, input_len:], skip_special_tokens=True)
        elapsed = time.perf_counter() - started
        mark_activity()
        return {
            "text": text,
            "duration": duration,
            "meta_info": {
                "infer_seconds": round(elapsed, 3),
                "completion_tokens": int(generated_ids.shape[1] - input_len),
                "cuda_memory": cuda_memory_stats(),
            },
        }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    hotwords: str = Form(default=""),
    max_new_tokens: int = Form(default=2048),
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
        payload = generate(
            GenerateRequest(
                text=build_transcription_prompt(hotwords),
                audio_data=str(tmp_path),
                sampling_params={
                    "max_new_tokens": int(max_new_tokens or 2048),
                    "temperature": 0.0,
                },
            )
        )
        payload["segments"] = [
            {
                "start_time": 0.0,
                "end_time": payload.get("duration", 0.0),
                "text": payload.get("text", ""),
            }
        ]
        return payload
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--quantization", choices=["none", "bnb-8bit", "bnb-4bit"], default="none")
    parser.add_argument(
        "--idle-unload-seconds",
        type=float,
        default=float(os.environ.get("MOSS_AUDIO_IDLE_UNLOAD_SECONDS", "10") or 10),
        help="Unload the model from GPU memory after this many idle seconds. Set 0 to disable.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=30000)
    return parser.parse_args()


def load_audio_file(path: Path, *, sample_rate: int):
    audio, original_sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if audio.shape[1] > 1:
        audio = audio.mean(axis=1)
    else:
        audio = audio[:, 0]
    if int(original_sample_rate) != int(sample_rate):
        audio = resample_poly(audio, int(sample_rate), int(original_sample_rate)).astype("float32")
    return audio


def audio_duration(audio: Any, *, sample_rate: int) -> float:
    try:
        return round(len(audio) / float(sample_rate), 3) if sample_rate > 0 else 0.0
    except TypeError:
        return 0.0


def build_transcription_prompt(hotwords: str | None) -> str:
    prompt = "Please transcribe this audio exactly. Output only the transcript text, with no explanation."
    terms = str(hotwords or "").strip()
    if not terms:
        return prompt
    return (
        f"{prompt}\n\n"
        "Pay special attention to these possible domain terms and preserve alphanumeric model names exactly: "
        f"{terms}."
    )


def build_quantization_config(value: str) -> BitsAndBytesConfig | None:
    if value == "none":
        return None
    if value == "bnb-8bit":
        return BitsAndBytesConfig(load_in_8bit=True)
    if value == "bnb-4bit":
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    raise ValueError(f"unsupported quantization mode: {value}")


def ensure_model_loaded() -> None:
    global loaded_seconds, load_count, last_loaded_at, model, processor
    if model is not None and processor is not None:
        return
    started = time.perf_counter()
    device_map = "cuda:0" if torch.cuda.is_available() else "cpu"
    quantization_config = build_quantization_config(quantization)
    model_kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "device_map": device_map,
    }
    if quantization_config is None:
        model_kwargs["dtype"] = "auto"
    else:
        model_kwargs["quantization_config"] = quantization_config
    next_model = MossAudioModel.from_pretrained(
        model_path,
        **model_kwargs,
    )
    next_model.eval()
    next_processor = MossAudioProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        enable_time_marker=True,
    )
    model = next_model
    processor = next_processor
    loaded_seconds = round(time.perf_counter() - started, 3)
    last_loaded_at = time.time()
    load_count += 1
    mark_activity()


def unload_model() -> None:
    global last_unloaded_at, model, processor
    if model is None and processor is None:
        return
    model = None
    processor = None
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

    def _monitor() -> None:
        while True:
            time.sleep(min(30.0, max(1.0, idle_unload_seconds / 4.0)))
            if model is None and processor is None:
                continue
            idle_for = time.monotonic() - last_activity_monotonic
            if idle_for < idle_unload_seconds:
                continue
            if not model_lock.acquire(blocking=False):
                continue
            try:
                if time.monotonic() - last_activity_monotonic >= idle_unload_seconds:
                    unload_model()
            finally:
                model_lock.release()

    thread = threading.Thread(target=_monitor, name="moss-audio-idle-unloader", daemon=True)
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


def main() -> None:
    global idle_unload_seconds, model_path, quantization
    args = parse_args()
    model_path = args.model_path
    quantization = args.quantization
    idle_unload_seconds = max(0.0, float(args.idle_unload_seconds or 0.0))
    with model_lock:
        ensure_model_loaded()
    start_idle_unload_monitor()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
