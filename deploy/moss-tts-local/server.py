from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import os
import tempfile
import threading
import time
import uuid
import wave
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from transformers import AutoModel, AutoProcessor, GenerationConfig

app = FastAPI(title="RoughCut MOSS-TTS Local 1.7B")
processor: Any | None = None
model: Any | None = None
model_id = ""
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if device == "cuda" else torch.float32
sample_rate = 24000
inference_lock = threading.Lock()
active_inference: dict[str, Any] = {}
stream_sessions: dict[str, dict[str, Any]] = {}
stream_sessions_lock = threading.Lock()
_STREAM_SESSION_MAX_INACTIVITY_SECONDS = 1200.0
_MOSS_TTS_SESSION_MODE_ALIASES = {
    "moss_duration_control": "moss_direct_tts",
}


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


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


def _audio_to_pcm16_bytes(audio: Any) -> bytes:
    if isinstance(audio, torch.Tensor):
        audio = audio.detach().float().cpu().numpy()
    audio_array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio_array.size == 0:
        raise HTTPException(status_code=502, detail="MOSS-TTS Local returned empty audio")
    audio_array = np.clip(audio_array, -1.0, 1.0)
    return (audio_array * 32767.0).astype("<i2").tobytes()


def _audio_to_wav_bytes(audio: Any) -> bytes:
    output = io.BytesIO()
    pcm16 = _audio_to_pcm16_bytes(audio)
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16)
    return output.getvalue()


def _audio_to_wav_response(audio: Any) -> Response:
    return Response(content=_audio_to_wav_bytes(audio), media_type="audio/wav")


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


def _run_moss_tts_local_generate(
    text: str,
    *,
    mode: str,
    prompt_text: str,
    duration_tokens: int,
    max_new_tokens: int,
    audio_temperature: float,
    audio_top_p: float,
    audio_top_k: int,
    audio_repetition_penalty: float,
    n_vq_for_inference: int,
    continuation: bool,
    seed: int,
    max_generation_seconds: float,
    reference_path: str | None,
) -> bytes:
    proc, loaded_model = _require_model()
    resolved_text = str(text or "").strip()
    if not resolved_text:
        raise HTTPException(status_code=400, detail="tts_text is required")

    acquired = inference_lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MOSS-TTS Local is already generating audio; retry after the active request finishes",
        )

    try:
        resolved_mode = str(mode or "").strip().lower()
        direct_mode = resolved_mode in {"direct_tts", "moss_direct_tts"}
        if not direct_mode and not reference_path:
            raise HTTPException(status_code=400, detail="prompt_wav/reference_audio is required for voice cloning")

        token_budget = int(duration_tokens or 0) or max(1, int(max_new_tokens or 2048))
        if reference_path and _bool(continuation) and str(prompt_text or "").strip():
            conversations = [[
                proc.build_user_message(text=str(prompt_text).strip() + resolved_text),
                proc.build_assistant_message(audio_codes_list=[reference_path]),
            ]]
            process_mode = "continuation"
        else:
            kwargs: dict[str, Any] = {"text": resolved_text}
            if reference_path:
                kwargs["reference"] = [reference_path]
            if int(duration_tokens or 0) > 0:
                kwargs["tokens"] = int(duration_tokens)
            conversations = [[proc.build_user_message(**kwargs)]]
            process_mode = "generation"

        batch = proc(conversations, mode=process_mode)
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        active_inference.clear()
        active_inference.update(
            {
                "mode": resolved_mode,
                "process_mode": process_mode,
                "text_chars": len(resolved_text),
                "token_budget": int(token_budget),
                "started_at": time.time(),
            }
        )
        gen_config = _generation_config(
            model_id,
            audio_temperature=audio_temperature,
            audio_top_p=audio_top_p,
            audio_top_k=audio_top_k,
            audio_repetition_penalty=audio_repetition_penalty,
            n_vq_for_inference=n_vq_for_inference,
        )
        resolved_seed = int(seed or 0)
        if resolved_seed > 0:
            torch.manual_seed(resolved_seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(resolved_seed)

        max_time = max(1.0, min(600.0, float(max_generation_seconds or 0.0)))
        with torch.inference_mode():
            outputs = loaded_model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=token_budget,
                max_time=max_time,
                generation_config=gen_config,
            )
        messages = list(proc.decode(outputs))
        if not messages or not getattr(messages[0], "audio_codes_list", None):
            raise HTTPException(status_code=502, detail="MOSS-TTS Local returned no audio")
        return _audio_to_pcm16_bytes(messages[0].audio_codes_list[0])
    finally:
        active_inference.clear()
        inference_lock.release()


def _normalize_session_config(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "moss_voice_clone").strip().lower()
    mode = _MOSS_TTS_SESSION_MODE_ALIASES.get(mode, mode)
    prompt_text = str(payload.get("prompt_text") or "").strip()
    continuation = _coerce_bool(payload.get("continuation"), default=False)
    if continuation and mode != "moss_continuation_clone":
        continuation = False
    requires_prompt_audio = mode in {"moss_voice_clone", "moss_continuation_clone"}
    return {
        "mode": mode,
        "prompt_text": prompt_text,
        "is_continuation": continuation,
        "requires_prompt_audio": requires_prompt_audio,
        "duration_tokens": _coerce_int(payload.get("duration_tokens"), 0),
        "max_new_tokens": _coerce_int(payload.get("max_new_tokens"), 2048),
        "audio_temperature": _coerce_float(payload.get("audio_temperature"), 1.0),
        "audio_top_p": _coerce_float(payload.get("audio_top_p"), 0.95),
        "audio_top_k": _coerce_int(payload.get("audio_top_k"), 50),
        "audio_repetition_penalty": _coerce_float(payload.get("audio_repetition_penalty"), 1.1),
        "n_vq_for_inference": _coerce_int(payload.get("n_vq_for_inference"), 32),
        "seed": max(0, _coerce_int(payload.get("seed"), 0)),
        "max_generation_seconds": _coerce_float(payload.get("max_generation_seconds"), 240.0),
    }


def _stream_session_worker(session_id: str) -> None:
    while True:
        chunk_text: str | None = None
        session: dict[str, Any] | None = None
        with stream_sessions_lock:
            session = stream_sessions.get(session_id)
            if session is None:
                return
            session["last_seen"] = time.time()
            if session.get("closed"):
                return
            if session.get("error"):
                return
            pending = session.setdefault("pending_chunks", deque())
            if pending:
                chunk_text = pending.popleft()
            elif session.get("is_final"):
                session["finished"] = True
                return
            else:
                # Wait for next push.
                session = None

        if session is None and chunk_text is None:
            time.sleep(0.05)
            continue

        if not chunk_text:
            continue

        try:
            pcm = _run_moss_tts_local_generate(
                chunk_text,
                mode=session["mode"],
                prompt_text=session["prompt_text"],
                duration_tokens=session["duration_tokens"],
                max_new_tokens=session["max_new_tokens"],
                audio_temperature=session["audio_temperature"],
                audio_top_p=session["audio_top_p"],
                audio_top_k=session["audio_top_k"],
                audio_repetition_penalty=session["audio_repetition_penalty"],
                n_vq_for_inference=session["n_vq_for_inference"],
                continuation=session["is_continuation"] and not session.get("chunked"),
                seed=session["seed"],
                max_generation_seconds=session["max_generation_seconds"],
                reference_path=session.get("reference_path"),
            )
            with stream_sessions_lock:
                active = stream_sessions.get(session_id)
                if active is None or active.get("closed"):
                    return
                active["chunks"].append(base64.b64encode(pcm).decode("ascii"))
                active["produced_chunks"] = int(active.get("produced_chunks", 0)) + 1
                active["chunked"] = True
                active["last_seen"] = time.time()
        except Exception as exc:
            with stream_sessions_lock:
                active = stream_sessions.get(session_id)
                if active is not None:
                    active["error"] = f"{type(exc).__name__}: {exc}"
                    active["finished"] = True
            return


def _start_session_worker(session_id: str) -> None:
    threading.Thread(target=_stream_session_worker, args=(session_id,), daemon=True).start()


def _close_session(session_id: str) -> dict[str, Any] | None:
    with stream_sessions_lock:
        session = stream_sessions.get(session_id)
        if session is None:
            return None
        if session.get("closed"):
            return session
        session["closed"] = True
        session["last_seen"] = time.time()
        if reference_path := session.get("reference_path"):
            Path(reference_path).unlink(missing_ok=True)
        return session


def _cleanup_idle_sessions() -> None:
    now = time.time()
    stale: list[str] = []
    with stream_sessions_lock:
        for session_id, session in stream_sessions.items():
            if session.get("closed") and session.get("finished", False):
                stale.append(session_id)
                continue
            if session.get("finished") and now - float(session.get("last_seen") or 0.0) > _STREAM_SESSION_MAX_INACTIVITY_SECONDS:
                stale.append(session_id)
    for session_id in stale:
        _close_session(session_id)


@app.get("/health")
def health() -> dict[str, Any]:
    _cleanup_idle_sessions()
    _require_model()
    return {
        "status": "ok",
        "provider": "official-moss-tts-local",
        "model": model_id,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "sample_rate": sample_rate,
        "busy": inference_lock.locked(),
        "active_inference": dict(active_inference),
        "active_stream_sessions": len(stream_sessions),
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
            "seed",
        ],
        "streaming": {
            "supports_session_api": True,
            "start": "/tts/session/start",
            "push": "/tts/session/push",
            "audio": "/tts/session/{session_id}/audio",
            "close": "/tts/session/close",
            "abort": "/tts/session/abort",
        },
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
    seed: int = Form(default=0),
    max_generation_seconds: float = Form(default=240.0),
    prompt_wav: UploadFile | None = File(default=None),
    reference_audio: UploadFile | None = File(default=None),
) -> Response:
    resolved_text = str(tts_text or text or "").strip()
    if not resolved_text:
        raise HTTPException(status_code=400, detail="tts_text is required")

    prompt_path = _save_upload(prompt_wav or reference_audio)
    config = _normalize_session_config(
        {
            "mode": mode,
            "prompt_text": prompt_text,
            "duration_tokens": duration_tokens,
            "max_new_tokens": max_new_tokens,
            "audio_temperature": audio_temperature,
            "audio_top_p": audio_top_p,
            "audio_top_k": audio_top_k,
            "audio_repetition_penalty": audio_repetition_penalty,
            "n_vq_for_inference": n_vq_for_inference,
            "seed": seed,
            "max_generation_seconds": max_generation_seconds,
            "continuation": continuation,
        }
    )

    try:
        pcm = _run_moss_tts_local_generate(
            resolved_text,
            mode=config["mode"],
            prompt_text=config["prompt_text"],
            duration_tokens=config["duration_tokens"],
            max_new_tokens=config["max_new_tokens"],
            audio_temperature=config["audio_temperature"],
            audio_top_p=config["audio_top_p"],
            audio_top_k=config["audio_top_k"],
            audio_repetition_penalty=config["audio_repetition_penalty"],
            n_vq_for_inference=config["n_vq_for_inference"],
            continuation=config["is_continuation"],
            seed=config["seed"],
            max_generation_seconds=config["max_generation_seconds"],
            reference_path=prompt_path,
        )
        return Response(content=_audio_to_wav_bytes(pcm), media_type="audio/wav")
    finally:
        if prompt_path:
            Path(prompt_path).unlink(missing_ok=True)


@app.post("/tts/session/start")
def session_start(
    mode: str = Form(default="moss_voice_clone"),
    tts_text: str = Form(default=""),
    text: str = Form(default=""),
    assistant_text: str = Form(default=""),
    user_text: str = Form(default=""),
    prompt_text: str = Form(default=""),
    max_new_tokens: int = Form(default=2048),
    duration_tokens: int = Form(default=0),
    audio_temperature: float = Form(default=1.0),
    audio_top_p: float = Form(default=0.95),
    audio_top_k: int = Form(default=50),
    audio_repetition_penalty: float = Form(default=1.1),
    n_vq_for_inference: int = Form(default=32),
    continuation: bool = Form(default=False),
    seed: int = Form(default=0),
    max_generation_seconds: float = Form(default=240.0),
    session_id: str = Form(default=""),
    prompt_wav: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    config = _normalize_session_config(
        {
            "mode": mode,
            "prompt_text": prompt_text,
            "duration_tokens": duration_tokens,
            "max_new_tokens": max_new_tokens,
            "audio_temperature": audio_temperature,
            "audio_top_p": audio_top_p,
            "audio_top_k": audio_top_k,
            "audio_repetition_penalty": audio_repetition_penalty,
            "n_vq_for_inference": n_vq_for_inference,
            "seed": seed,
            "max_generation_seconds": max_generation_seconds,
            "continuation": continuation,
        }
    )

    start_text = str(assistant_text or user_text or tts_text or text or "").strip()
    resolved_session_id = str(session_id or str(uuid.uuid4())).strip()
    if config["requires_prompt_audio"] and not prompt_wav:
        raise HTTPException(
            status_code=400,
            detail="prompt_wav is required for moss_voice_clone and moss_continuation_clone",
        )

    prompt_path = _save_upload(prompt_wav)
    now = time.time()
    with stream_sessions_lock:
        if resolved_session_id in stream_sessions:
            raise HTTPException(status_code=409, detail="session_id already exists")

        stream_sessions[resolved_session_id] = {
            "session_id": resolved_session_id,
            "mode": config["mode"],
            "prompt_text": config["prompt_text"],
            "duration_tokens": config["duration_tokens"],
            "max_new_tokens": config["max_new_tokens"],
            "audio_temperature": config["audio_temperature"],
            "audio_top_p": config["audio_top_p"],
            "audio_top_k": config["audio_top_k"],
            "audio_repetition_penalty": config["audio_repetition_penalty"],
            "n_vq_for_inference": config["n_vq_for_inference"],
            "is_continuation": config["is_continuation"],
            "seed": config["seed"],
            "max_generation_seconds": config["max_generation_seconds"],
            "reference_path": prompt_path,
            "pending_chunks": deque(),
            "chunks": [],
            "produced_chunks": 0,
            "chunked": False,
            "is_final": False,
            "finished": False,
            "error": None,
            "closed": False,
            "created_at": now,
            "last_seen": now,
        }

        if start_text:
            stream_sessions[resolved_session_id]["pending_chunks"].append(start_text)

    _start_session_worker(resolved_session_id)
    return {
        "session_id": resolved_session_id,
        "status": "started",
        "requires_prompt": bool(config["requires_prompt_audio"]),
        "queued": 1 if start_text else 0,
        "is_final": False,
    }


@app.post("/tts/session/push")
def session_push(
    session_id: str = Form(default=""),
    text: str = Form(default=""),
    is_final: bool = Form(default=False),
) -> dict[str, Any]:
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    with stream_sessions_lock:
        session = stream_sessions.get(resolved_session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if session.get("closed"):
            raise HTTPException(status_code=409, detail="session is closed")
        if session.get("error"):
            raise HTTPException(status_code=409, detail=session.get("error"))

        delta = str(text or "")
        if delta:
            session["pending_chunks"].append(delta)
        if is_final:
            session["is_final"] = True

        return {
            "session_id": resolved_session_id,
            "queued": len(session["pending_chunks"]),
            "is_final": bool(session["is_final"]),
        }


@app.get("/tts/session/{session_id}/audio")
def session_audio(session_id: str, after: int = 0) -> dict[str, Any]:
    with stream_sessions_lock:
        session = stream_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        session["last_seen"] = time.time()
        chunks = session.get("chunks", [])
        start = max(0, min(int(after), len(chunks)))
        pending = chunks[start:]

        return {
            "session_id": session_id,
            "next_after": start + len(pending),
            "audio_chunks": [
                {
                    "index": start + idx,
                    "audio_base64": chunk,
                }
                for idx, chunk in enumerate(pending)
            ],
            "finished": bool(session.get("finished")),
            "error": session.get("error"),
            "sample_rate": sample_rate,
            "channels": 1,
            "codec": "pcm_s16le",
        }


@app.post("/tts/session/close")
def session_close(session_id: str = Form(default="")) -> dict[str, Any]:
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    with stream_sessions_lock:
        session = stream_sessions.get(resolved_session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        session["is_final"] = True
        session["closed"] = True
    return {
        "session_id": resolved_session_id,
        "status": "closing",
        "queued": len(session["pending_chunks"]),
        "finished": bool(session["finished"]),
    }


@app.post("/tts/session/abort")
def session_abort(session_id: str = Form(default="")) -> dict[str, Any]:
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    session = _close_session(resolved_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session_id": resolved_session_id,
        "status": "aborted",
        "error": session.get("error"),
    }


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
