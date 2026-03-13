from __future__ import annotations

import io
import json
import math
import os
import subprocess
import random
import shutil
import time
import wave
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.responses import Response


app = FastAPI(title="RoughCut HeyGem Mock")

ROOT = Path(os.getenv("HEYGEM_SHARED_ROOT", "/code/data"))
TASKS: dict[str, dict] = {}
TASK_LOCK = Lock()


def _ensure_dirs() -> None:
    (ROOT / "inputs" / "audio").mkdir(parents=True, exist_ok=True)
    (ROOT / "inputs" / "video").mkdir(parents=True, exist_ok=True)
    (ROOT / "temp").mkdir(parents=True, exist_ok=True)
    (ROOT / "result").mkdir(parents=True, exist_ok=True)
    (ROOT / "voice").mkdir(parents=True, exist_ok=True)
    (ROOT / "voice" / "data").mkdir(parents=True, exist_ok=True)


def _to_local_path(candidate: str) -> Path:
    value = str(candidate or "").strip()
    if not value:
        return Path()
    if value.startswith("http://") or value.startswith("https://"):
        return Path()
    if value.startswith("/code/data/"):
        return ROOT / value.removeprefix("/code/data/").lstrip("/")
    if value == "/code/data":
        return ROOT
    if value.startswith("/"):
        return ROOT / value.lstrip("/")
    return ROOT / value


def _make_wav_bytes(duration_sec: float = 2.0) -> bytes:
    sample_rate = 16000
    duration_sec = max(0.5, min(30.0, float(duration_sec)))
    total_frames = int(sample_rate * duration_sec)
    pcm = bytearray()
    for _ in range(total_frames):
        sample = int(2048 * math.sin(time.time()))
        pcm.extend(int(sample).to_bytes(2, byteorder="little", signed=True))

    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        return buffer.getvalue()


def _make_result_path(task_code: str) -> Path:
    _ensure_dirs()
    return ROOT / "result" / f"{task_code}.mp4"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/json")
def openapi_like_paths() -> dict[str, dict]:
    return {
        "paths": {
            "/v1/preprocess_and_tran": {},
            "/v1/invoke": {},
            "/easy/submit": {},
            "/easy/query": {},
            "/v1/submit": {},
            "/v1/query": {},
            "/api/easy/submit": {},
            "/api/easy/query": {},
            "/submit": {},
            "/query": {},
        }
    }


@app.post("/v1/health")
def training_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/preprocess_and_tran")
async def preprocess_and_tran(request: Request) -> dict[str, object]:
    payload = await request.json()
    reference_audio = str(payload.get("reference_audio") or "").strip()
    return {
        "code": 0,
        "reference_audio_text": f"{reference_audio} sample",
        "asr_format_audio_url": reference_audio or "",
    }


@app.post("/v1/invoke")
async def invoke(request: Request) -> Response:
    payload = await request.json()
    text = str(payload.get("text") or "")
    duration_sec = min(20.0, max(1.0, len(text) * 0.05))
    return Response(content=_make_wav_bytes(duration_sec), media_type="audio/wav")


def _set_task(task_code: str, payload: dict[str, object]) -> None:
    with TASK_LOCK:
        TASKS[task_code] = payload


def _get_task(task_code: str) -> dict | None:
    with TASK_LOCK:
        return TASKS.get(task_code)


def _register_task(task_code: str, video_url: str, audio_url: str) -> tuple[str, dict]:
    output_path = _make_result_path(task_code)
    src_video = _to_local_path(video_url)
    src_audio = _to_local_path(audio_url)
    if src_video.exists():
        _render_preview_video(
            task_code=task_code,
            source_video=src_video,
            source_audio=src_audio if src_audio.exists() else None,
            output_path=output_path,
        )
    else:
        # fallback: create a tiny valid mp4 placeholder via copy from temp input when available
        for candidate in ROOT.glob("inputs/video/*"):
            try:
                if candidate.is_file():
                    shutil.copy2(candidate, output_path)
                    break
            except Exception:
                continue
        if not output_path.exists():
            output_path.write_bytes(b"")

    payload = {
        "status": 2,
        "progress": 100,
        "result": f"/result/{output_path.name}",
        "video_duration": random.randint(1000, 2500),
        "width": 0,
        "height": 0,
        "msg": "mock completed",
    }
    _set_task(task_code, payload)
    return str(output_path), payload


@app.post("/easy/submit")
@app.post("/v1/easy/submit")
@app.post("/api/easy/submit")
@app.post("/submit")
@app.post("/v1/submit")
async def submit(request: Request) -> dict[str, object]:
    payload = await request.json()
    task_code = str(payload.get("code") or "")
    if not task_code:
        return {"code": -1, "msg": "missing code", "data": None}
    _register_task(
        task_code,
        str(payload.get("video_url") or ""),
        str(payload.get("audio_url") or ""),
    )
    return {
        "code": 10000,
        "msg": "accepted",
        "task_code": task_code,
        "data": {"code": task_code},
    }


@app.get("/easy/query")
@app.get("/v1/easy/query")
@app.get("/api/easy/query")
@app.get("/query")
@app.get("/v1/query")
async def query(code: str) -> dict[str, object]:
    task = _get_task(code)
    if task is None:
        return {"code": 10000, "data": {"code": code, "status": 1, "msg": "processing", "progress": 10}}
    return {
        "code": 10000,
        "data": {
            "code": code,
            "status": task.get("status"),
            "progress": task.get("progress"),
            "result": task.get("result"),
            "video_duration": task.get("video_duration"),
            "width": task.get("width"),
            "height": task.get("height"),
            "msg": task.get("msg"),
        },
    }


def _render_preview_video(*, task_code: str, source_video: Path, source_audio: Path | None, output_path: Path) -> None:
    task_label = task_code[:12]
    watermark = (
        "drawbox=x=0:y=0:w=iw:h=ih*0.12:color=black@0.25:t=fill,"
        "eq=contrast=1.2:brightness=-0.03:saturation=1.12,"
        f"drawbox=x=16:y=16:w=380:h=50:color=yellow@0.45:t=fill"
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_video),
        "-vf",
        watermark,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "28",
    ]

    if source_audio is not None:
        command.extend(
            [
                "-i",
                str(source_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
            ]
        )
    else:
        command.append("-an")

    command.append(str(output_path))

    fallback_command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_video),
        "-vf",
        "hflip,eq=contrast=1.05:brightness=0.02:saturation=1.12",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "30",
    ]
    if source_audio is not None:
        fallback_command.extend(
            [
                "-i",
                str(source_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
            ]
        )
    else:
        fallback_command.append("-an")

    fallback_command.append(str(output_path))

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return
    except Exception:
        pass

    try:
        fallback_result = subprocess.run(fallback_command, capture_output=True, text=True, timeout=30)
        if fallback_result.returncode == 0 and output_path.exists():
            return
    except Exception:
        pass

    safe_pattern_command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=640x360:rate=30:duration=3",
        "-vf",
        (
            "drawbox=x=16:y=16:w=420:h=60:color=yellow@0.4:t=fill,"
            "drawbox=x=0:y=0:w=iw:h=ih*0.1:color=black@0.22:t=fill,"
            "eq=contrast=1.08"
        ),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        "3",
        str(output_path),
    ]
    fallback_safe = subprocess.run(safe_pattern_command, capture_output=True, text=True, timeout=20)
    if fallback_safe.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"mock preview rendering failed: {fallback_safe.stderr[-1000:]}")
