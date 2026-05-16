from __future__ import annotations

import argparse
import importlib.util
import io
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from transformers import AutoModel, AutoProcessor, GenerationConfig

app = FastAPI(title="RoughCut MOSS-TTS Local 1.7B")
processor: Any | None = None
model: Any | None = None
model_id = ""
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if device == "cuda" else torch.float32
sample_rate = 24000


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _save_upload(upload: UploadFile | None) -> str | None:
    if upload is None:
        return None
    suffix = Path(upload.filename or "").suffix or ".wav"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    finally:
        handle.close()
    return handle.name


def _require_model() -> tuple[Any, Any]:
    if processor is None or model is None:
        raise HTTPException(status_code=503, detail="MOSS-TTS Local model is still loading")
    return processor, model


def _resolve_attn_implementation() -> str:
    if device == "cuda" and importlib.util.find_spec("flash_attn") is not None and dtype in {torch.float16, torch.bfloat16}:
        major, _ = torch.cuda.get_device_capability()
        if major >= 8:
            return "flash_attention_2"
    if device == "cuda":
        return "sdpa"
    return "eager"


def _audio_to_wav_response(audio: Any) -> Response:
    if isinstance(audio, torch.Tensor):
        audio = audio.detach().float().cpu().numpy()
    audio_array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio_array.size == 0:
        raise HTTPException(status_code=502, detail="MOSS-TTS Local returned empty audio")
    audio_array = np.clip(audio_array, -1.0, 1.0)
    pcm16 = (audio_array * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16)
    return Response(content=output.getvalue(), media_type="audio/wav")


def _generation_config(
    model_dir: str,
    *,
    audio_temperature: float,
    audio_top_p: float,
    audio_top_k: int,
    audio_repetition_penalty: float,
    n_vq_for_inference: int,
) -> GenerationConfig:
    config = GenerationConfig.from_pretrained(model_dir, trust_remote_code=True)
    config.audio_temperature = max(0.0, float(audio_temperature))
    config.audio_top_p = min(1.0, max(0.01, float(audio_top_p)))
    config.audio_top_k = max(1, int(audio_top_k))
    config.audio_repetition_penalty = max(0.01, float(audio_repetition_penalty))
    config.n_vq_for_inference = max(1, min(32, int(n_vq_for_inference)))
    return config


@app.get("/health")
def health() -> dict[str, Any]:
    _require_model()
    return {
        "status": "ok",
        "provider": "official-moss-tts-local",
        "model": model_id,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "sample_rate": sample_rate,
    }


@app.get("/query_tts_model")
@app.post("/query_tts_model")
def query_tts_model() -> dict[str, Any]:
    _require_model()
    return {
        "model": model_id,
        "sample_rate": sample_rate,
        "modes": ["direct_tts", "moss_voice_clone", "moss_continuation_clone"],
        "params": [
            "mode",
            "tts_text",
            "prompt_wav",
            "max_new_tokens",
            "duration_tokens",
            "audio_temperature",
            "audio_top_p",
            "audio_top_k",
            "audio_repetition_penalty",
            "n_vq_for_inference",
            "continuation",
        ],
    }


@app.post("/inference")
def inference(
    mode: str = Form(default="moss_voice_clone"),
    tts_text: str = Form(default=""),
    text: str = Form(default=""),
    prompt_text: str = Form(default=""),
    max_new_tokens: int = Form(default=2048),
    duration_tokens: int = Form(default=0),
    audio_temperature: float = Form(default=1.0),
    audio_top_p: float = Form(default=0.95),
    audio_top_k: int = Form(default=50),
    audio_repetition_penalty: float = Form(default=1.1),
    n_vq_for_inference: int = Form(default=32),
    continuation: bool = Form(default=False),
    prompt_wav: UploadFile | None = File(default=None),
    reference_audio: UploadFile | None = File(default=None),
) -> Response:
    proc, loaded_model = _require_model()
    resolved_text = str(tts_text or text or "").strip()
    if not resolved_text:
        raise HTTPException(status_code=400, detail="tts_text is required")
    prompt_path = _save_upload(prompt_wav or reference_audio)
    try:
        resolved_mode = str(mode or "").strip().lower()
        direct_mode = resolved_mode in {"direct_tts", "moss_direct_tts"}
        if not direct_mode and not prompt_path:
            raise HTTPException(status_code=400, detail="prompt_wav/reference_audio is required for voice cloning")
        token_budget = int(duration_tokens or 0) or max(1, int(max_new_tokens or 2048))
        if prompt_path and _bool(continuation) and str(prompt_text or "").strip():
            conversations = [[
                proc.build_user_message(text=str(prompt_text).strip() + resolved_text),
                proc.build_assistant_message(audio_codes_list=[prompt_path]),
            ]]
            process_mode = "continuation"
        else:
            kwargs: dict[str, Any] = {"text": resolved_text}
            if prompt_path:
                kwargs["reference"] = [prompt_path]
            if int(duration_tokens or 0) > 0:
                kwargs["tokens"] = int(duration_tokens)
            conversations = [[proc.build_user_message(**kwargs)]]
            process_mode = "generation"

        batch = proc(conversations, mode=process_mode)
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        gen_config = _generation_config(
            model_id,
            audio_temperature=audio_temperature,
            audio_top_p=audio_top_p,
            audio_top_k=audio_top_k,
            audio_repetition_penalty=audio_repetition_penalty,
            n_vq_for_inference=n_vq_for_inference,
        )
        with torch.inference_mode():
            outputs = loaded_model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=token_budget,
                generation_config=gen_config,
            )
        messages = list(proc.decode(outputs))
        if not messages or not getattr(messages[0], "audio_codes_list", None):
            raise HTTPException(status_code=502, detail="MOSS-TTS Local returned no audio")
        return _audio_to_wav_response(messages[0].audio_codes_list[0])
    finally:
        if prompt_path:
            Path(prompt_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model_dir", default=os.environ.get("MOSS_TTS_LOCAL_MODEL_DIR") or os.environ.get("MOSS_TTS_LOCAL_MODEL_ID"))
    args = parser.parse_args()

    torch.backends.cuda.enable_cudnn_sdp(False)
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(True)

    global processor, model, model_id, sample_rate
    model_id = str(args.model_dir or "OpenMOSS-Team/MOSS-TTS-Local-Transformer")
    attn_implementation = _resolve_attn_implementation()
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    processor.audio_tokenizer = processor.audio_tokenizer.to(device)
    model = AutoModel.from_pretrained(
        model_id,
        trust_remote_code=True,
        attn_implementation=attn_implementation,
        torch_dtype=dtype,
    ).to(device)
    model.eval()
    sample_rate = int(getattr(processor.model_config, "sampling_rate", sample_rate))

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
