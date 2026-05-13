from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

ROOT_DIR = Path(os.environ.get("COSYVOICE_REPO_DIR", "/opt/CosyVoice")).resolve()
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402
from cosyvoice.utils.common import set_all_random_seed  # noqa: E402

app = FastAPI(title="RoughCut CosyVoice3 TTS")
cosyvoice: Any | None = None
model_id = ""
END_OF_PROMPT = "<|endofprompt|>"
SYSTEM_PROMPT = "You are a helpful assistant."
INSTRUCT_MAX_CHARS = 160


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


def _require_model() -> Any:
    if cosyvoice is None:
        raise HTTPException(status_code=503, detail="CosyVoice3 model is still loading")
    return cosyvoice


def _require_end_of_prompt(value: str, field_name: str) -> None:
    if END_OF_PROMPT not in str(value or ""):
        raise HTTPException(
            status_code=400,
            detail=f"CosyVoice3 {field_name} must include {END_OF_PROMPT}",
        )


def _strip_prompt_format(value: str) -> str:
    cleaned = str(value or "").replace(END_OF_PROMPT, "").strip()
    if cleaned.startswith(SYSTEM_PROMPT):
        cleaned = cleaned[len(SYSTEM_PROMPT):].strip()
    return cleaned


def _normalize_zero_shot_prompt_text(value: str) -> str:
    body = _strip_prompt_format(value)
    if not body:
        return ""
    return f"{SYSTEM_PROMPT}{END_OF_PROMPT}{body}"


def _normalize_instruct_text(value: str) -> str:
    body = _compact_instruct_text(value)
    if not body:
        return ""
    return f"{SYSTEM_PROMPT}\n{body}{END_OF_PROMPT}"


def _compact_instruct_text(value: str) -> str:
    body = _strip_prompt_format(value)
    if not body:
        return ""
    for separator in ("；", ";"):
        body = body.replace(separator, "\n")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    compact_lines: list[str] = []
    seen: set[str] = set()
    for line in lines or [body.strip()]:
        compact_line = _normalize_instruct_line(line)
        if not compact_line or compact_line in seen:
            continue
        candidate = "；".join([*compact_lines, compact_line])
        if len(candidate) > INSTRUCT_MAX_CHARS:
            break
        compact_lines.append(compact_line)
        seen.add(compact_line)
    compact = "；".join(compact_lines)
    if len(compact) > INSTRUCT_MAX_CHARS:
        compact = _truncate_instruct_line(compact, max_chars=INSTRUCT_MAX_CHARS)
    return _ensure_sentence_punctuation(compact)


def _normalize_instruct_line(value: str) -> str:
    import re

    line = str(value or "").strip().strip("'\"").rstrip(",")
    line = re.sub(r"\s+", "", line)
    line = line.replace("这句话", "").replace("一句话", "").replace("进行表达", "表达")
    line = re.sub(r"^请", "", line)
    line = re.sub(r"^像(.+?)一样[，,]?", r"\1风格，", line)
    line = re.sub(r"^用(.+?)(?:的方式)?(?:说|表达)[，,]?", r"\1，", line)
    line = line.replace("适合短视频旁白的方式", "短视频旁白风格")
    line = line.replace("更温柔", "温柔").replace("更清楚", "清楚")
    replacements = (
        ("声音亲切、有耐心，语气温柔活泼", "亲切耐心、温柔活泼"),
        ("有声故事演播风格表达", "故事演播"),
        ("有声故事演播风格", "故事演播"),
        ("语气有画面感", "画面感"),
        ("人物和情节转折要更清楚", "转折清楚"),
        ("人物和情节转折要清楚", "转折清楚"),
        ("课堂教学风格表达", "课堂教学"),
        ("课堂教学风格", "课堂教学"),
        ("重点词需要自然强调", "重点自然强调"),
        ("紧凑、有节奏、适合短视频旁白", "短视频旁白、紧凑有节奏"),
        ("紧凑、有节奏、短视频旁白风格", "短视频旁白、紧凑有节奏"),
        ("较慢语速表达", "较慢语速"),
        ("重点词上做清晰强调", "重点清晰强调"),
        ("语义分段处加入自然停顿", "语义分段自然停顿"),
        ("信息更容易理解", "信息易理解"),
    )
    for source, target in replacements:
        line = line.replace(source, target)
    line = line.replace("声音", "").replace("语气", "")
    line = line.replace("需要", "")
    line = line.replace("人物和情节转折要", "转折")
    line = line.replace("并在", "，").replace("上做", "")
    line = line.replace("加入", "").replace("让信息更容易理解", "信息易理解")
    line = line.replace("地说", "")
    line = line.replace("表达", "")
    line = re.sub(r"[，,、]{2,}", "，", line)
    return line.strip(" ，,。.")


def _truncate_instruct_line(value: str, *, max_chars: int) -> str:
    line = str(value or "").strip()
    if len(line) <= max_chars:
        return line
    for separator in ("，", ",", "、"):
        index = line.rfind(separator, 0, max_chars + 1)
        if index >= max(8, int(max_chars * 0.45)):
            return line[:index].strip(" ，,、")
    return line[:max_chars].strip(" ，,、")


def _ensure_sentence_punctuation(value: str) -> str:
    line = str(value or "").strip()
    if not line:
        return ""
    return line if line[-1] in "。.!！？" else f"{line}。"


def _audio_to_wav_response(chunks: Iterable[dict[str, Any]], sample_rate: int) -> Response:
    audio_parts: list[np.ndarray] = []
    for chunk in chunks:
        speech = chunk.get("tts_speech")
        if speech is None:
            continue
        if isinstance(speech, torch.Tensor):
            speech = speech.detach().cpu().numpy()
        audio_parts.append(np.asarray(speech, dtype=np.float32).reshape(-1))
    if not audio_parts:
        raise HTTPException(status_code=502, detail="CosyVoice3 returned empty audio")
    audio = np.concatenate(audio_parts)
    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767.0).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16)
    return Response(content=output.getvalue(), media_type="audio/wav")


@app.get("/health")
def health() -> dict[str, Any]:
    model = _require_model()
    return {
        "status": "ok",
        "provider": "official-cosyvoice",
        "model": model_id,
        "sample_rate": int(getattr(model, "sample_rate", 24000)),
    }


@app.get("/query_tts_model")
@app.post("/query_tts_model")
def query_tts_model() -> dict[str, Any]:
    model = _require_model()
    speakers = model.list_available_spks() if hasattr(model, "list_available_spks") else []
    return {
        "model": model_id,
        "tts_models": speakers,
        "sample_rate": int(getattr(model, "sample_rate", 24000)),
        "modes": ["sft", "zero_shot", "cross_lingual", "instruct2"],
        "params": [
            "mode",
            "tts_text",
            "prompt_text",
            "prompt_wav",
            "spk_id",
            "instruct_text",
            "stream",
            "speed",
            "seed",
            "zero_shot_spk_id",
            "text_frontend",
        ],
    }


@app.post("/inference")
def inference(
    mode: str = Form(default="zero_shot"),
    tts_text: str = Form(default=""),
    text: str = Form(default=""),
    prompt_text: str = Form(default=""),
    spk_id: str = Form(default=""),
    instruct_text: str = Form(default=""),
    stream: bool = Form(default=False),
    speed: float = Form(default=1.0),
    seed: int = Form(default=0),
    zero_shot_spk_id: str = Form(default=""),
    text_frontend: bool = Form(default=True),
    prompt_wav: UploadFile | None = File(default=None),
    reference_audio: UploadFile | None = File(default=None),
) -> Response:
    model = _require_model()
    resolved_text = str(tts_text or text or "").strip()
    resolved_mode = str(mode or "zero_shot").strip().lower()
    prompt_path = _save_upload(prompt_wav or reference_audio)
    try:
        if not resolved_text:
            raise HTTPException(status_code=400, detail="tts_text is required")
        if stream and abs(float(speed or 1.0) - 1.0) > 0.0001:
            raise HTTPException(status_code=400, detail="stream=true requires speed=1")
        if int(seed or 0) > 0:
            set_all_random_seed(int(seed))

        call: Callable[..., Any]
        kwargs: dict[str, Any] = {"stream": stream, "speed": float(speed or 1.0), "text_frontend": _bool(text_frontend)}
        if resolved_mode == "sft":
            if not spk_id:
                raise HTTPException(status_code=400, detail="spk_id is required for sft mode")
            call = model.inference_sft
            chunks = call(resolved_text, spk_id, **kwargs)
        elif resolved_mode == "zero_shot":
            if not prompt_path:
                raise HTTPException(status_code=400, detail="prompt_wav is required for zero_shot mode")
            if not str(prompt_text or "").strip():
                raise HTTPException(status_code=400, detail="prompt_text is required for zero_shot mode")
            prompt_text = _normalize_zero_shot_prompt_text(prompt_text)
            call = model.inference_zero_shot
            chunks = call(resolved_text, prompt_text, prompt_path, zero_shot_spk_id=zero_shot_spk_id, **kwargs)
        elif resolved_mode == "cross_lingual":
            if not prompt_path:
                raise HTTPException(status_code=400, detail="prompt_wav is required for cross_lingual mode")
            call = model.inference_cross_lingual
            chunks = call(resolved_text, prompt_path, zero_shot_spk_id=zero_shot_spk_id, **kwargs)
        elif resolved_mode in {"instruct", "instruct2"}:
            if not prompt_path:
                raise HTTPException(status_code=400, detail="prompt_wav is required for instruct2 mode")
            if not str(instruct_text or "").strip():
                raise HTTPException(status_code=400, detail="instruct_text is required for instruct2 mode")
            instruct_text = _normalize_instruct_text(instruct_text)
            call = getattr(model, "inference_instruct2", None)
            if call is None:
                raise HTTPException(status_code=400, detail="current model does not support instruct2")
            chunks = call(resolved_text, instruct_text, prompt_path, zero_shot_spk_id=zero_shot_spk_id, **kwargs)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported mode: {mode}")
        return _audio_to_wav_response(chunks, sample_rate=int(getattr(model, "sample_rate", 24000)))
    finally:
        if prompt_path:
            Path(prompt_path).unlink(missing_ok=True)


@app.post("/inference_zero_shot")
def inference_zero_shot(
    tts_text: str = Form(default=""),
    text: str = Form(default=""),
    prompt_text: str = Form(default=""),
    stream: bool = Form(default=False),
    speed: float = Form(default=1.0),
    seed: int = Form(default=0),
    zero_shot_spk_id: str = Form(default=""),
    text_frontend: bool = Form(default=True),
    prompt_wav: UploadFile | None = File(default=None),
    reference_audio: UploadFile | None = File(default=None),
) -> Response:
    return inference(
        mode="zero_shot",
        tts_text=tts_text,
        text=text,
        prompt_text=prompt_text,
        stream=stream,
        speed=speed,
        seed=seed,
        zero_shot_spk_id=zero_shot_spk_id,
        text_frontend=text_frontend,
        prompt_wav=prompt_wav,
        reference_audio=reference_audio,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model_dir", default=os.environ.get("COSYVOICE3_MODEL_DIR") or os.environ.get("COSYVOICE3_MODEL_ID"))
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--load_vllm", action="store_true")
    parser.add_argument("--load_trt", action="store_true")
    parser.add_argument("--trt_concurrent", type=int, default=1)
    args = parser.parse_args()

    global cosyvoice, model_id
    model_id = str(args.model_dir or "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
    cosyvoice = AutoModel(
        model_dir=model_id,
        fp16=args.fp16,
        load_vllm=args.load_vllm,
        load_trt=args.load_trt,
        trt_concurrent=args.trt_concurrent,
    )

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
