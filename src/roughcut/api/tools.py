from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import subprocess
import uuid
import wave
from pathlib import Path, PureWindowsPath
from typing import Any, Callable
from urllib.parse import quote

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from roughcut.config import DEFAULT_OUTPUT_ROOT, get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.providers.avatar.heygem import HeyGemAvatarProvider
from roughcut.providers.transcription.base import TranscriptResult
from roughcut.providers.transcription.local_http_asr import LocalHTTPASRProvider

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOLS_ROOT = DEFAULT_OUTPUT_ROOT / "tools"
_TTS_ROOT = _TOOLS_ROOT / "tts"
_ASR_UPLOAD_ROOT = _TOOLS_ROOT / "asr-uploads"
_AVATAR_ROOT = _TOOLS_ROOT / "avatar"
_UPLOAD_ROOT = _TOOLS_ROOT / "uploads"
_REFERENCE_UPLOAD_ROOT = _TOOLS_ROOT / "reference-uploads"
_REFERENCE_ROOT = _TOOLS_ROOT / "reference-cache"
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_TASKS: dict[str, asyncio.Task[None]] = {}
_RUN_STAGE_NAMES: tuple[str, ...] = (
    "upload",
    "validate",
    "service_start",
    "request",
    "process",
    "write_artifact",
    "completed",
    "failed",
)
_RUN_PROGRESS_FLOORS: dict[str, float] = {
    "upload": 0.02,
    "validate": 0.08,
    "service_start": 0.18,
    "request": 0.34,
    "process": 0.55,
    "write_artifact": 0.86,
    "completed": 1.0,
    "failed": 1.0,
}
_COSYVOICE3_END_OF_PROMPT = "<|endofprompt|>"
_TTS_TEXT_SEGMENT_MAX_CHARS = 120
_TTS_TEXT_HARD_BOUNDARY_CHARS = frozenset("。！？!?；;….")
_TTS_TEXT_SOFT_BOUNDARY_CHARS = frozenset("，,、：:")
_MAX_REFERENCE_AUDIO_SEC = 30.0
_REFERENCE_AUDIO_HISTORY_LIMIT = 5
_TTS_OUTPUT_HISTORY_LIMIT = 10
_REFERENCE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
_REFERENCE_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_TTS_TEXT_UI_HINTS: tuple[str, ...] = (
    "需要 prompt_wav/reference_audio；只填写想要的口播指令，官方分隔符由后台自动补齐。",
    "需要 prompt_wav/reference_audio；只填写参考音频里实际说过的文本，官方分隔符由后台自动补齐。",
    "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。",
    "需要填写 /query_tts_model 返回的 spk_id；如果模型没有内置音色列表，此模式不可用。",
)
_TTS_PRIMARY_TEXT_KEYS: tuple[str, ...] = (
    "tts_text",
    "ttsText",
    "spoken_text",
    "spokenText",
    "voiceover_text",
    "voiceoverText",
    "narration_text",
    "narrationText",
)
_TTS_SEGMENT_TEXT_KEYS: tuple[str, ...] = (
    "rewritten_text",
    "rewrittenText",
    "script",
    "text",
)
_TTS_SEGMENT_KEYS: tuple[str, ...] = (
    "voiceover_segments",
    "voiceoverSegments",
    "segments",
    "items",
)
_TTS_NESTED_PAYLOAD_KEYS: tuple[str, ...] = (
    "dubbing_request",
    "result",
    "payload",
    "data",
)
_TTS_TEXT_LABEL_RE = re.compile(
    r"(?im)^\s*(?:[\"']?(?:tts_text|ttsText|spoken_text|voiceover_text|narration_text)[\"']?|朗读正文|配音正文|口播正文)\s*[:：=]\s*(?P<value>.+?)\s*$"
)
_TTS_TEXT_BLOCK_LABEL_RE = re.compile(
    r"(?is)(?:^|\n)\s*(?:[\"']?(?:tts_text|ttsText|spoken_text|voiceover_text|narration_text)[\"']?|朗读正文|配音正文|口播正文)\s*[:：=]\s*(?P<value>.+)$"
)
_TTS_STRUCTURED_FIELD_LABEL_RE = re.compile(
    r"(?i)^\s*[\"']?(?:prompt|prompt_text|instruct_text|purpose|source_text|reason|rewrite_strategy|opening_hook|voiceover_segments|target_duration_sec|suggested_start_time)[\"']?\s*[:：=]"
)
_STRUCTURED_TTS_PROMPT_MARKERS: tuple[str, ...] = (
    "voiceover_segments",
    "source_text",
    "opening_hook",
    "rewrite_strategy",
    "target_duration_sec",
    "suggested_start_time",
    "输出 JSON",
    "JSON 结构",
    "你是短视频 AI 导演",
    "你是严谨的中文短视频导演",
    "请根据字幕",
    "要求：",
    "结构化",
)

@router.get("/status")
async def tools_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "tools": {
            "tts": await _probe_tts_service(
                base_url=settings.cosyvoice3_tts_api_base_url,
                name="CosyVoice3 TTS",
            ),
            "asr": await _probe_json_service(
                base_url=settings.local_asr_api_base_url,
                path=settings.local_asr_health_path,
                name=settings.local_asr_display_name or "Local HTTP ASR",
            ),
            "avatar": await _probe_avatar_service(settings.avatar_api_base_url),
        },
    }


@router.post("/tts")
async def run_tts(
    mode: str = Form(default="zero_shot"),
    text: str = Form(default=""),
    tts_text: str = Form(default=""),
    prompt_text: str = Form(default=""),
    instruct_text: str = Form(default=""),
    spk_id: str = Form(default=""),
    zero_shot_spk_id: str = Form(default=""),
    stream: bool = Form(default=True),
    speed: float = Form(default=1.0),
    seed: int = Form(default=0),
    text_frontend: bool = Form(default=True),
    reference_history_path: str = Form(default=""),
    reference_audio: UploadFile | None = File(default=None),
    prompt_wav: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    try:
        normalized_text = _resolve_tts_spoken_text(tts_text or text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not normalized_text:
        raise HTTPException(status_code=400, detail="text is required")

    reference_path = await _save_upload(
        prompt_wav or reference_audio,
        root=_REFERENCE_UPLOAD_ROOT,
        fallback_suffix=".wav",
    )
    if reference_path is None and str(reference_history_path or "").strip():
        reference_path = _resolve_reference_audio_history_path(reference_history_path)
    run = _create_run("tts")
    _update_run_stage(run["run_id"], "upload", detail="TTS request accepted")
    _schedule_run(
        run["run_id"],
        _execute_tts_run,
        run["run_id"],
        text=normalized_text,
        original_text=normalized_text,
        mode=mode,
        prompt_text=prompt_text,
        instruct_text=instruct_text,
        spk_id=spk_id,
        zero_shot_spk_id=zero_shot_spk_id,
        stream=stream,
        speed=speed,
        seed=seed,
        text_frontend=text_frontend,
        reference_path=reference_path,
    )
    return _run_public_payload(run)


@router.get("/tts/reference-audio")
async def list_tts_reference_audio() -> dict[str, Any]:
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": _list_reference_audio_history(),
    }


@router.get("/tts/outputs")
async def list_tts_outputs() -> dict[str, Any]:
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": _list_tts_output_history(),
    }


@router.post("/asr")
async def run_asr(
    audio: UploadFile = File(...),
    language: str = Form(default="zh-CN"),
    prompt: str = Form(default=""),
) -> dict[str, Any]:
    audio_path = await _save_upload(audio, root=_ASR_UPLOAD_ROOT, fallback_suffix=".wav")
    if audio_path is None:
        raise HTTPException(status_code=400, detail="audio is required")

    run = _create_run("asr")
    _update_run_stage(run["run_id"], "upload", detail="ASR audio uploaded", progress=0.04, path=str(audio_path))
    _schedule_run(
        run["run_id"],
        _execute_asr_run,
        run["run_id"],
        audio_path=audio_path,
        language=language or "zh-CN",
        prompt=prompt or "",
    )
    return _run_public_payload(run)


@router.post("/avatar")
async def run_avatar(
    script: str = Form(default=""),
    presenter_video: UploadFile = File(...),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    presenter_path = await _save_upload(presenter_video, root=_UPLOAD_ROOT, fallback_suffix=".mp4")
    audio_path = await _save_upload(audio, root=_UPLOAD_ROOT, fallback_suffix=".wav")
    if presenter_path is None or audio_path is None:
        raise HTTPException(status_code=400, detail="presenter_video and audio are required")

    run = _create_run("avatar")
    _update_run_stage(
        run["run_id"],
        "upload",
        detail="Avatar source media uploaded",
        progress=0.04,
        presenter_path=str(presenter_path),
        audio_path=str(audio_path),
    )
    _schedule_run(
        run["run_id"],
        _execute_avatar_run,
        run["run_id"],
        script=script,
        presenter_path=presenter_path,
        audio_path=audio_path,
    )
    return _run_public_payload(run)


@router.get("/runs/{run_id}")
async def get_tool_run(run_id: str) -> dict[str, Any]:
    run = _RUNS.get(str(run_id or "").strip())
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_public_payload(run)


async def _execute_tts_run(
    run_id: str,
    *,
    text: str,
    original_text: str,
    mode: str,
    prompt_text: str,
    instruct_text: str,
    spk_id: str,
    zero_shot_spk_id: str,
    stream: bool,
    speed: float,
    seed: int,
    text_frontend: bool,
    reference_path: Path | None,
) -> None:
    settings = get_settings()
    _TTS_ROOT.mkdir(parents=True, exist_ok=True)
    _update_run_stage(
        run_id,
        "validate",
        detail="Validated TTS form fields",
        mode=mode,
        stream=stream,
        speed=speed,
    )
    resolved_mode = str(mode or "zero_shot").strip().lower()
    if resolved_mode in {"zero_shot", "cross_lingual", "instruct", "instruct2"} and reference_path is None:
        raise RuntimeError(f"CosyVoice3 {resolved_mode} TTS requires prompt_wav/reference_audio")
    user_prompt_text = _strip_cosyvoice_prompt_boundary(prompt_text)
    resolved_prompt_text = _normalize_cosyvoice3_prompt_text(user_prompt_text) if resolved_mode == "zero_shot" else user_prompt_text
    user_instruct_text = _strip_cosyvoice_prompt_boundary(instruct_text)
    resolved_instruct_text = _normalize_cosyvoice3_instruct_text(user_instruct_text) if resolved_mode in {"instruct", "instruct2"} else user_instruct_text
    if resolved_mode == "zero_shot" and not user_prompt_text:
        raise RuntimeError("CosyVoice3 zero_shot TTS requires prompt_text")
    if resolved_mode in {"instruct", "instruct2"} and not user_instruct_text:
        raise RuntimeError("CosyVoice3 instruct2 TTS requires instruct_text")
    polluted_fragments = [fragment for fragment in (user_prompt_text, user_instruct_text) if fragment and fragment in text]
    if polluted_fragments:
        raise RuntimeError("朗读正文包含参考文本或口播指令；请保持 tts_text 只包含实际需要说出口的正文")
    if resolved_mode == "sft" and not str(spk_id or "").strip():
        raise RuntimeError("CosyVoice3 sft TTS requires spk_id from /query_tts_model")
    if stream and abs(float(speed or 1.0) - 1.0) > 0.0001:
        raise RuntimeError("CosyVoice3 streaming mode requires speed=1; use stream=false for speed changes")
    if reference_path is not None:
        reference_path = _prepare_reference_audio_for_cosyvoice(reference_path, run_id=run_id)
    text_segments = _split_tts_text_for_synthesis(text)
    if not text_segments:
        raise RuntimeError("text is required")
    endpoint = "/inference"
    base_data: dict[str, str] = {
        "mode": resolved_mode,
        "prompt_text": resolved_prompt_text,
        "instruct_text": resolved_instruct_text,
        "spk_id": str(spk_id or "").strip(),
        "zero_shot_spk_id": str(zero_shot_spk_id or "").strip(),
        "stream": "true" if stream else "false",
        "speed": str(float(speed or 1.0)),
        "seed": str(int(seed or 0)),
        "text_frontend": "true" if text_frontend else "false",
    }
    segment_output_paths: list[Path] = []
    response: httpx.Response | None = None
    sample_rate = int(settings.cosyvoice3_tts_sample_rate or 24000)

    try:
        _update_run_stage(run_id, "service_start", detail="Starting CosyVoice3 TTS service")
        async with hold_managed_gpu_services_async(
            required_urls=[settings.cosyvoice3_tts_api_base_url],
            reason="tools_tts_cosyvoice3",
        ):
            _update_run_stage(
                run_id,
                "request",
                detail=(
                    f"Submitting CosyVoice3 {resolved_mode} request"
                    if len(text_segments) == 1
                    else f"Submitting CosyVoice3 {resolved_mode} request 1/{len(text_segments)}"
                ),
                endpoint=endpoint,
                request_fields=sorted([*base_data.keys(), "tts_text", "text"]),
                mode=resolved_mode,
                segment_count=len(text_segments),
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=20.0), follow_redirects=True) as client:
                for index, segment_text in enumerate(text_segments, start=1):
                    segment_data = _build_tts_segment_form_data(base_data, segment_text)
                    if len(text_segments) > 1:
                        _update_run_stage(
                            run_id,
                            "request",
                            detail=f"Submitting CosyVoice3 {resolved_mode} request {index}/{len(text_segments)}",
                            progress=0.34 + ((index - 1) / max(len(text_segments), 1)) * 0.36,
                            endpoint=endpoint,
                            mode=resolved_mode,
                            segment_index=index,
                            segment_count=len(text_segments),
                        )
                    response = await _post_tts_segment_request(
                        client,
                        f"{settings.cosyvoice3_tts_api_base_url.rstrip('/')}{endpoint}",
                        data=segment_data,
                        reference_path=reference_path,
                    )
                    response.raise_for_status()
                    if len(text_segments) > 1:
                        _update_run_stage(
                            run_id,
                            "process",
                            detail=f"CosyVoice3 response received {index}/{len(text_segments)}",
                            progress=0.55 + (index / max(len(text_segments), 1)) * 0.24,
                            segment_index=index,
                            segment_count=len(text_segments),
                        )
                        segment_path = _TTS_ROOT / f"tts_{run_id}_{index:03d}.segment.wav"
                        _write_tts_response_audio(response, output_path=segment_path, sample_rate=sample_rate)
                        segment_output_paths.append(segment_path)
        _update_run_stage(run_id, "process", detail="CosyVoice3 response received")
    except httpx.HTTPStatusError as exc:
        _cleanup_paths(segment_output_paths)
        detail = _read_response_error(exc.response)
        raise RuntimeError(f"CosyVoice3 TTS failed: {detail}") from exc
    except Exception as exc:
        _cleanup_paths(segment_output_paths)
        raise RuntimeError(f"CosyVoice3 TTS unavailable: {exc}") from exc

    output_path = _TTS_ROOT / f"tts_{uuid.uuid4().hex[:12]}.wav"
    _update_run_stage(run_id, "write_artifact", detail="Writing synthesized audio", output_path=str(output_path))
    try:
        if len(text_segments) == 1:
            if response is None:
                raise RuntimeError("CosyVoice3 did not return a response")
            meta = _write_tts_response_audio(response, output_path=output_path, sample_rate=sample_rate)
        else:
            meta = _concatenate_tts_wav_segments(segment_output_paths, output_path=output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        _cleanup_paths(segment_output_paths)
    _complete_run(run_id, {
        "status": "success",
        "provider": "official-cosyvoice3",
        "mode": resolved_mode,
        "text": text,
        "tts_text": text,
        "original_text": original_text,
        "prompt_text": user_prompt_text,
        "instruct_text": user_instruct_text,
        "spk_id": spk_id,
        "zero_shot_spk_id": zero_shot_spk_id,
        "stream": stream,
        "speed": float(speed or 1.0),
        "seed": int(seed or 0),
        "text_frontend": text_frontend,
        "output_path": str(output_path),
        "audio_url": f"/api/v1/tools/artifacts/tts/{output_path.name}",
        "segment_count": len(text_segments),
        "text_segments": [
            {"index": index, "text": segment_text, "char_count": len(segment_text)}
            for index, segment_text in enumerate(text_segments, start=1)
        ],
        **meta,
    })


def _build_tts_segment_form_data(base_data: dict[str, str], text: str) -> dict[str, str]:
    data = dict(base_data)
    data["tts_text"] = text
    data["text"] = text
    return data


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


async def _post_tts_segment_request(
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict[str, str],
    reference_path: Path | None,
) -> httpx.Response:
    files = None
    if reference_path is not None:
        reference_handle = reference_path.open("rb")
        files = {
            "prompt_wav": (reference_path.name, reference_handle, "application/octet-stream"),
        }
    try:
        return await client.post(url, data=data, files=files)
    finally:
        if files is not None:
            files["prompt_wav"][1].close()


def _split_tts_text_for_synthesis(text: str, *, max_chars: int = _TTS_TEXT_SEGMENT_MAX_CHARS) -> list[str]:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return []
    max_chars = max(1, int(max_chars or _TTS_TEXT_SEGMENT_MAX_CHARS))
    if len(normalized) <= max_chars:
        return [normalized]

    sentence_units = _split_tts_text_units(normalized, boundary_chars=_TTS_TEXT_HARD_BOUNDARY_CHARS)
    segments: list[str] = []
    current = ""
    for sentence in sentence_units:
        for part in _split_tts_long_unit(sentence, max_chars=max_chars):
            if not current:
                current = part
                continue
            candidate = _join_tts_text_parts(current, part)
            if len(candidate) <= max_chars:
                current = candidate
                continue
            segments.append(current)
            current = part
    if current:
        segments.append(current)
    return [segment for segment in segments if segment.strip()]


def _split_tts_text_units(text: str, *, boundary_chars: frozenset[str]) -> list[str]:
    units: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if _is_tts_text_boundary(text, index, boundary_chars=boundary_chars):
            unit = text[start:index + 1].strip()
            if unit:
                units.append(unit)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units or [text]


def _is_tts_text_boundary(text: str, index: int, *, boundary_chars: frozenset[str]) -> bool:
    char = text[index]
    if char not in boundary_chars:
        return False
    if char == ".":
        previous_char = text[index - 1] if index > 0 else ""
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if previous_char.isdigit() and next_char.isdigit():
            return False
    return True


def _split_tts_long_unit(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    soft_units = _split_tts_text_units(text, boundary_chars=_TTS_TEXT_SOFT_BOUNDARY_CHARS)
    parts: list[str] = []
    current = ""
    for unit in soft_units:
        if len(unit) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(_hard_split_tts_text(unit, max_chars=max_chars))
            continue
        candidate = _join_tts_text_parts(current, unit) if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        parts.append(current)
        current = unit
    if current:
        parts.append(current)
    return parts


def _hard_split_tts_text(text: str, *, max_chars: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = _find_tts_hard_split_index(remaining, max_chars=max_chars)
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _find_tts_hard_split_index(text: str, *, max_chars: int) -> int:
    lower_bound = max(1, int(max_chars * 0.6))
    for index in range(max_chars, lower_bound, -1):
        if text[index - 1].isspace():
            return index
    return max_chars


def _join_tts_text_parts(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    separator = " " if left[-1].isascii() and right[0].isascii() and not left[-1].isspace() else ""
    return f"{left}{separator}{right}"


def _concatenate_tts_wav_segments(segment_paths: list[Path], *, output_path: Path) -> dict[str, Any]:
    if not segment_paths:
        raise RuntimeError("CosyVoice3 returned no segment audio")
    params: Any | None = None
    with wave.open(str(output_path), "wb") as output:
        for segment_path in segment_paths:
            with wave.open(str(segment_path), "rb") as segment:
                segment_params = segment.getparams()
                if params is None:
                    params = segment_params
                    output.setnchannels(segment_params.nchannels)
                    output.setsampwidth(segment_params.sampwidth)
                    output.setframerate(segment_params.framerate)
                    output.setcomptype(segment_params.comptype, segment_params.compname)
                elif (
                    segment_params.nchannels != params.nchannels
                    or segment_params.sampwidth != params.sampwidth
                    or segment_params.framerate != params.framerate
                    or segment_params.comptype != params.comptype
                ):
                    raise RuntimeError("CosyVoice3 segment audio formats do not match")
                output.writeframes(segment.readframes(segment.getnframes()))
    sample_rate = int(params.framerate) if params is not None else 0
    return {
        "format": "wav",
        "sample_rate": sample_rate,
        "source_format": "segmented_wav",
        "duration": _probe_audio_duration(output_path),
    }


def _strip_cosyvoice_prompt_boundary(value: str | None) -> str:
    cleaned = str(value or "").replace(_COSYVOICE3_END_OF_PROMPT, "").strip()
    if cleaned.startswith(_COSYVOICE3_SYSTEM_PROMPT):
        cleaned = cleaned[len(_COSYVOICE3_SYSTEM_PROMPT):].strip()
    return cleaned


def _strip_tts_text_ui_hints(value: str | None) -> str:
    return _collapse_tts_text(_remove_tts_text_ui_hints(value))


def _remove_tts_text_ui_hints(value: str | None) -> str:
    cleaned = str(value or "").strip()
    for hint in _TTS_TEXT_UI_HINTS:
        cleaned = cleaned.replace(hint, "").strip()
    return cleaned


def _collapse_tts_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _resolve_tts_spoken_text(value: str | None) -> str:
    cleaned = _remove_tts_text_ui_hints(value)
    structured_text = _extract_structured_tts_text(cleaned)
    if structured_text:
        resolved = _collapse_tts_text(structured_text)
        if _looks_like_structured_tts_prompt(resolved):
            raise ValueError("可朗读的 tts_text 里仍包含结构化提示词；请只保留实际要说出口的正文")
        return resolved
    if _looks_like_structured_tts_prompt(cleaned):
        raise ValueError("结构化提示词里没有找到可朗读的 tts_text；请把实际要说出口的正文放到 tts_text")
    return _collapse_tts_text(cleaned)


def _extract_structured_tts_text(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    payload = _parse_structured_tts_payload(raw)
    candidate = _extract_tts_text_candidate(payload)
    if candidate:
        return _sanitize_extracted_tts_text(candidate)
    labeled_text = _extract_labeled_tts_text(raw)
    if labeled_text:
        return _sanitize_extracted_tts_text(labeled_text)
    return ""


def _parse_structured_tts_payload(value: str) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return None
    fence_match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", raw, flags=re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    candidates = [raw]
    object_start = raw.find("{")
    object_end = raw.rfind("}")
    if 0 <= object_start < object_end:
        candidates.append(raw[object_start:object_end + 1])
    list_start = raw.find("[")
    list_end = raw.rfind("]")
    if 0 <= list_start < list_end:
        candidates.append(raw[list_start:list_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
    return None


def _extract_tts_text_candidate(payload: Any) -> str:
    if isinstance(payload, str):
        return _sanitize_extracted_tts_text(payload)
    if isinstance(payload, list):
        parts = [_extract_tts_text_candidate(item) for item in payload]
        return "\n".join(part for part in parts if part)
    if not isinstance(payload, dict):
        return ""
    for key in _TTS_PRIMARY_TEXT_KEYS:
        candidate = _string_tts_candidate(payload.get(key))
        if candidate:
            return candidate
    for key in _TTS_SEGMENT_KEYS:
        candidate = _extract_tts_text_candidate(payload.get(key))
        if candidate:
            return candidate
    for key in _TTS_NESTED_PAYLOAD_KEYS:
        candidate = _extract_tts_text_candidate(payload.get(key))
        if candidate:
            return candidate
    for key in _TTS_SEGMENT_TEXT_KEYS:
        candidate = _string_tts_candidate(payload.get(key))
        if candidate:
            return candidate
    return ""


def _string_tts_candidate(value: Any) -> str:
    if isinstance(value, str):
        return _strip_wrapping_quotes(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        parts = [_string_tts_candidate(item) for item in value]
        return "\n".join(part for part in parts if part)
    return ""


def _strip_wrapping_quotes(value: str) -> str:
    cleaned = str(value or "").strip().rstrip(",")
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def _extract_labeled_tts_text(value: str) -> str:
    raw = str(value or "").strip()
    block_match = _TTS_TEXT_BLOCK_LABEL_RE.search(raw)
    if block_match:
        return _trim_structured_field_tail(block_match.group("value"))
    line_match = _TTS_TEXT_LABEL_RE.search(raw)
    if line_match:
        return line_match.group("value")
    return ""


def _trim_structured_field_tail(value: str) -> str:
    lines: list[str] = []
    for line in str(value or "").splitlines():
        if lines and _TTS_STRUCTURED_FIELD_LABEL_RE.match(line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _sanitize_extracted_tts_text(value: str) -> str:
    cleaned = _strip_wrapping_quotes(value)
    if not cleaned:
        return ""
    nested_payload = _parse_structured_tts_payload(cleaned)
    if nested_payload is not None:
        nested_candidate = _extract_tts_text_candidate(nested_payload)
        if nested_candidate and nested_candidate != cleaned:
            return nested_candidate
    labeled_text = _extract_labeled_tts_text(cleaned)
    if labeled_text and labeled_text != cleaned:
        return _sanitize_extracted_tts_text(labeled_text)
    if _looks_like_structured_tts_prompt(cleaned):
        raise ValueError("可朗读的 tts_text 里仍包含结构化提示词；请只保留实际要说出口的正文")
    return cleaned


def _looks_like_structured_tts_prompt(value: str | None) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw.startswith(("```", "{", "[")):
        return True
    return any(marker in raw for marker in _STRUCTURED_TTS_PROMPT_MARKERS)


def _ensure_cosyvoice_prompt_boundary(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    if _COSYVOICE3_END_OF_PROMPT in raw:
        return raw
    return f"{raw}{_COSYVOICE3_END_OF_PROMPT}"


_COSYVOICE3_SYSTEM_PROMPT = "You are a helpful assistant."


def _normalize_cosyvoice3_prompt_text(value: str) -> str:
    body = str(value or "").strip()
    if not body:
        return ""
    return f"{_COSYVOICE3_SYSTEM_PROMPT}{_COSYVOICE3_END_OF_PROMPT}{body}"


def _normalize_cosyvoice3_instruct_text(value: str) -> str:
    body = str(value or "").strip()
    if not body:
        return ""
    if body.startswith(_COSYVOICE3_SYSTEM_PROMPT):
        body = body[len(_COSYVOICE3_SYSTEM_PROMPT):].strip()
    return f"{_COSYVOICE3_SYSTEM_PROMPT} {body}{_COSYVOICE3_END_OF_PROMPT}"


async def _execute_asr_run(run_id: str, *, audio_path: Path, language: str, prompt: str) -> None:
    _update_run_stage(run_id, "validate", detail="Validated ASR audio input")
    provider = LocalHTTPASRProvider()

    def on_progress(payload: dict[str, Any]) -> None:
        provider_progress = _coerce_progress(payload.get("progress"))
        mapped_progress = None if provider_progress is None else 0.36 + (provider_progress * 0.46)
        phase = str(payload.get("phase") or "process").strip()
        _update_run_stage(
            run_id,
            "process",
            detail=str(payload.get("detail") or f"ASR {phase}"),
            progress=mapped_progress,
            provider_progress=provider_progress,
            provider_phase=phase,
            provider_payload=_compact_progress_payload(payload),
        )

    try:
        settings = get_settings()
        _update_run_stage(run_id, "service_start", detail="Starting Local HTTP ASR service")
        async with hold_managed_gpu_services_async(
            required_urls=[settings.local_asr_api_base_url],
            reason="tools_asr_local_http",
        ):
            _update_run_stage(run_id, "request", detail="Submitting ASR transcribe request")
            result = await provider.transcribe(
                audio_path,
                language=language or "zh-CN",
                prompt=prompt or None,
                progress_callback=on_progress,
            )
        _update_run_stage(run_id, "write_artifact", detail="Preparing ASR transcript payload")
    except Exception as exc:
        raise RuntimeError(f"ASR failed: {exc}") from exc
    _complete_run(run_id, _transcript_result_to_payload(result))


async def _execute_avatar_run(run_id: str, *, script: str, presenter_path: Path, audio_path: Path) -> None:
    _update_run_stage(run_id, "validate", detail="Validated avatar render inputs")
    job_id = f"tool-avatar-{uuid.uuid4().hex[:10]}"
    provider = HeyGemAvatarProvider()
    request = {
        "provider": "heygem",
        "job_id": job_id,
        "presenter_id": str(presenter_path),
        "segments": [
            {
                "segment_id": "preview",
                "script": str(script or "").strip(),
                "audio_url": str(audio_path),
                "duration_sec": _probe_audio_duration(audio_path),
            }
        ],
    }
    try:
        settings = get_settings()
        _update_run_stage(run_id, "service_start", detail="Starting HeyGem avatar service")
        async with hold_managed_gpu_services_async(
            required_urls=[settings.avatar_api_base_url],
            reason="tools_avatar_heygem",
        ):
            _update_run_stage(run_id, "request", detail="Submitting avatar render job", job_id=job_id)
            result = await asyncio.to_thread(provider.execute_render, job_id=job_id, request=request)
        _update_run_stage(run_id, "process", detail="Avatar render completed by service", job_id=job_id)
        artifact = _copy_avatar_result(result)
        _update_run_stage(run_id, "write_artifact", detail="Copied avatar render artifact")
    except Exception as exc:
        raise RuntimeError(f"Avatar render failed: {exc}") from exc

    _complete_run(run_id, {
        **result,
        "artifact_url": f"/api/v1/tools/artifacts/avatar/{artifact.name}" if artifact else None,
        "artifact_path": str(artifact) if artifact else None,
    })


async def _run_background(run_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        await func(*args, **kwargs)
    except Exception as exc:
        _fail_run(run_id, str(exc))
    finally:
        _RUN_TASKS.pop(run_id, None)


def _schedule_run(run_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    _RUN_TASKS[run_id] = asyncio.create_task(_run_background(run_id, func, *args, **kwargs))


def _create_run(tool: str) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": run_id,
        "tool": tool,
        "status": "queued",
        "progress": 0.0,
        "created_at": now,
        "updated_at": now,
        "stages": [
            {
                "name": name,
                "status": "pending",
                "progress": 0.0,
                "detail": "",
                "updated_at": None,
            }
            for name in _RUN_STAGE_NAMES
        ],
        "result": None,
        "error": None,
    }
    _RUNS[run_id] = run
    return run


def _update_run_stage(run_id: str, stage_name: str, *, detail: str = "", progress: float | None = None, **extra: Any) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    stage = _get_run_stage(run, stage_name)
    if stage is None:
        return
    run["status"] = "running"
    stage["status"] = "running"
    stage["detail"] = detail or stage.get("detail") or ""
    stage["updated_at"] = now
    if extra:
        stage.setdefault("data", {}).update(_json_safe(extra))
    resolved_progress = _coerce_progress(progress)
    if resolved_progress is None:
        resolved_progress = _RUN_PROGRESS_FLOORS.get(stage_name, float(run.get("progress") or 0.0))
    stage["progress"] = max(float(stage.get("progress") or 0.0), resolved_progress)
    run["progress"] = max(float(run.get("progress") or 0.0), stage["progress"])
    run["updated_at"] = now
    _mark_prior_stages_done(run, stage_name, now)


def _complete_run(run_id: str, result: dict[str, Any]) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    _mark_prior_stages_done(run, "completed", now)
    stage = _get_run_stage(run, "completed")
    if stage is not None:
        stage.update({"status": "completed", "progress": 1.0, "detail": "Completed", "updated_at": now})
    failed = _get_run_stage(run, "failed")
    if failed is not None and failed["status"] == "pending":
        failed["progress"] = 0.0
    run.update({"status": "completed", "progress": 1.0, "result": result, "error": None, "updated_at": now})


def _fail_run(run_id: str, error: str) -> None:
    run = _RUNS.get(run_id)
    if run is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    for active_stage in run.get("stages", []):
        if active_stage.get("status") == "running":
            active_stage.update({
                "status": "failed",
                "progress": max(float(active_stage.get("progress") or 0.0), _RUN_PROGRESS_FLOORS.get(str(active_stage.get("name") or ""), 1.0)),
                "detail": error,
                "updated_at": now,
            })
    stage = _get_run_stage(run, "failed")
    if stage is not None:
        stage.update({"status": "failed", "progress": 1.0, "detail": error, "updated_at": now})
    run.update({"status": "failed", "progress": 1.0, "error": error, "updated_at": now})


def _get_run_stage(run: dict[str, Any], stage_name: str) -> dict[str, Any] | None:
    for stage in run.get("stages", []):
        if stage.get("name") == stage_name:
            return stage
    return None


def _mark_prior_stages_done(run: dict[str, Any], stage_name: str, updated_at: str) -> None:
    names = [stage.get("name") for stage in run.get("stages", [])]
    try:
        target_index = names.index(stage_name)
    except ValueError:
        return
    for stage in run.get("stages", [])[:target_index]:
        if stage.get("status") in {"pending", "running"}:
            stage["status"] = "completed"
            stage["progress"] = max(float(stage.get("progress") or 0.0), _RUN_PROGRESS_FLOORS.get(stage["name"], 0.0))
            stage["updated_at"] = updated_at


def _run_public_payload(run: dict[str, Any]) -> dict[str, Any]:
    current_stage = _current_stage_name(run)
    stages = [
        stage
        for stage in run.get("stages", [])
        if not (run.get("status") == "completed" and stage.get("name") == "failed" and stage.get("status") == "pending")
    ]
    return {
        "run_id": run["run_id"],
        "tool": run["tool"],
        "status": run["status"],
        "progress": run["progress"],
        "current_stage": current_stage,
        "detail": _current_stage_detail(run, current_stage),
        "stages": stages,
        "result": run.get("result"),
        "error": run.get("error"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }


def _current_stage_name(run: dict[str, Any]) -> str:
    if run.get("status") == "failed":
        return "failed"
    for stage in run.get("stages", []):
        if stage.get("status") == "running":
            return str(stage.get("name") or "")
    if run.get("status") == "completed":
        return "completed"
    return str(run.get("status") or "queued")


def _current_stage_detail(run: dict[str, Any], current_stage: str) -> str:
    stage = _get_run_stage(run, current_stage)
    if stage is None:
        return ""
    return str(stage.get("detail") or "")


def _coerce_progress(value: Any) -> float | None:
    try:
        progress = float(value)
    except (TypeError, ValueError):
        return None
    if progress > 1.0:
        progress = progress / 100.0
    return min(1.0, max(0.0, progress))


def _compact_progress_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in {"phase", "detail", "progress", "segment_count", "segment_end", "total_duration", "retry_attempt", "retry_count", "text"}
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _reference_audio_dedupe_key(path: Path, *, size: int, duration: float | None) -> str:
    try:
        digest = hashlib.sha1()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return f"sha1:{digest.hexdigest()}"
    except OSError:
        pass
    try:
        return f"path:{str(path.resolve()).casefold()}"
    except OSError:
        duration_key = "" if duration is None else f"{duration:.3f}"
        return f"meta:{path.name.casefold()}:{size}:{duration_key}"


def _list_audio_artifact_history(
    *,
    root: Path,
    source: str,
    artifact_kind: str,
    limit: int,
    suffixes: set[str],
    dedupe: bool,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    candidates: list[tuple[float, Path, str, int, float | None]] = []
    if not root.exists():
        return []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in suffixes or ".segment." in path.name:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        duration = _audio_duration_seconds(path)
        candidates.append((stat.st_mtime, path, source, stat.st_size, duration))
    candidates.sort(key=lambda item: item[0], reverse=True)
    unique_candidates: list[tuple[float, Path, str, int, float | None]] = []
    seen_keys: set[str] = set()
    for updated_at, path, source, size, duration in candidates:
        if dedupe:
            dedupe_key = _reference_audio_dedupe_key(path, size=size, duration=duration)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
        unique_candidates.append((updated_at, path, source, size, duration))
        if len(unique_candidates) >= limit:
            break
    return [
        {
            "name": path.name,
            "path": str(path),
            "source": source,
            "size": size,
            "duration": duration,
            "will_trim": (duration or 0.0) > _MAX_REFERENCE_AUDIO_SEC,
            "updated_at": datetime.fromtimestamp(updated_at, timezone.utc).isoformat(),
            "audio_url": f"/api/v1/tools/artifacts/{artifact_kind}/{quote(path.name)}",
        }
        for updated_at, path, source, size, duration in unique_candidates
    ]


def _list_reference_audio_history(limit: int = _REFERENCE_AUDIO_HISTORY_LIMIT) -> list[dict[str, Any]]:
    return _list_audio_artifact_history(
        root=_REFERENCE_UPLOAD_ROOT,
        source="参考上传",
        artifact_kind="reference-uploads",
        limit=limit,
        suffixes=_REFERENCE_AUDIO_SUFFIXES | _REFERENCE_VIDEO_SUFFIXES,
        dedupe=True,
    )


def _list_tts_output_history(limit: int = _TTS_OUTPUT_HISTORY_LIMIT) -> list[dict[str, Any]]:
    return _list_audio_artifact_history(
        root=_TTS_ROOT,
        source="生成音频",
        artifact_kind="tts",
        limit=limit,
        suffixes=_REFERENCE_AUDIO_SUFFIXES,
        dedupe=False,
    )


def _resolve_reference_audio_history_path(value: str) -> Path:
    requested = str(value or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="reference_history_path is empty")
    raw_path = Path(requested)
    allowed_roots = (_REFERENCE_UPLOAD_ROOT.resolve(),)
    candidates = [raw_path]
    if raw_path.name == requested:
        candidates.append(_REFERENCE_UPLOAD_ROOT / raw_path.name)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if any(resolved == root or root in resolved.parents for root in allowed_roots) and resolved.exists() and resolved.is_file():
            return resolved
    raise HTTPException(status_code=400, detail="reference_history_path is not available")


def _prepare_reference_audio_for_cosyvoice(path: Path, *, run_id: str) -> Path:
    suffix = path.suffix.lower()
    duration = _audio_duration_seconds(path)
    needs_conversion = suffix != ".wav"
    needs_trimming = duration is not None and duration > _MAX_REFERENCE_AUDIO_SEC
    if not needs_conversion and not needs_trimming:
        return path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if suffix in _REFERENCE_VIDEO_SUFFIXES:
            raise RuntimeError("参考视频需要 ffmpeg 自动提取音频并转换为 CosyVoice3 可用的 WAV")
        if needs_trimming and duration is not None:
            raise RuntimeError(f"参考音频 {duration:.1f}s 超过 30s；需要 ffmpeg 自动去除开头静音并截取 30s")
        raise RuntimeError("参考音频需要 ffmpeg 转换为 CosyVoice3 可用的 WAV")
    _REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = _REFERENCE_ROOT / f"reference_{uuid.uuid4().hex[:12]}.wav"
    if suffix in _REFERENCE_VIDEO_SUFFIXES:
        detail = "正在从参考视频提取音频，转换为 16k 单声道 WAV"
    elif needs_trimming and duration is not None:
        detail = f"参考音频 {duration:.1f}s 超过 30s，正在去除开头静音并截取 30s"
    else:
        detail = "正在转换参考音频为 16k 单声道 WAV"
    _update_run_stage(
        run_id,
        "validate",
        detail=detail,
        progress=0.12,
        reference_source=str(path),
        reference_duration=duration,
        reference_output=str(output_path),
    )
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-vn",
        "-af",
        "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-45dB",
    ]
    if duration is None or needs_trimming:
        command.extend(["-t", str(_MAX_REFERENCE_AUDIO_SEC)])
    command.extend([
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ])
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        fallback_command = [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-vn",
        ]
        if duration is None or needs_trimming:
            fallback_command.extend(["-t", str(_MAX_REFERENCE_AUDIO_SEC)])
        fallback_command.extend([
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ])
        fallback = subprocess.run(fallback_command, check=False, capture_output=True, text=True, timeout=90)
        if fallback.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
            output_path.unlink(missing_ok=True)
            detail = (fallback.stderr or result.stderr or "ffmpeg trim failed").strip().splitlines()[-1:]
            raise RuntimeError(f"Failed to prepare reference audio: {' '.join(detail)[:500]}")
    return output_path


def _audio_duration_seconds(path: Path) -> float | None:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                frame_rate = float(handle.getframerate() or 0)
                if frame_rate <= 0:
                    return None
                return float(handle.getnframes()) / frame_rate
        except (OSError, wave.Error, EOFError):
            pass
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return float(str(result.stdout or "").strip())
    except ValueError:
        return None


@router.get("/artifacts/{kind}/{file_name}")
async def get_tool_artifact(kind: str, file_name: str):
    root = {
        "tts": _TTS_ROOT,
        "avatar": _AVATAR_ROOT,
        "uploads": _UPLOAD_ROOT,
        "reference-uploads": _REFERENCE_UPLOAD_ROOT,
    }.get(kind)
    if root is None:
        raise HTTPException(status_code=404, detail="unknown artifact kind")
    path = (root / Path(file_name).name).resolve()
    if root.resolve() not in path.parents or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)


async def _probe_json_service(*, base_url: str, path: str, name: str) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    url = f"{str(base_url or '').rstrip('/')}{path if path.startswith('/') else f'/{path}'}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=1.5)) as client:
            response = await client.get(url)
        response.raise_for_status()
    except Exception as exc:
        return {"name": name, "base_url": base_url, "status": "offline", "checked_at": checked_at, "error": str(exc)}
    payload = response.json() if response.headers.get("content-type", "").lower().startswith("application/json") else {}
    return {"name": name, "base_url": base_url, "status": "online", "checked_at": checked_at, "detail": payload}


async def _probe_tts_service(*, base_url: str, name: str) -> dict[str, Any]:
    settings = get_settings()
    health = await _probe_json_service(
        base_url=base_url,
        path=settings.cosyvoice3_tts_health_path,
        name=name,
    )
    model_url = f"{str(base_url or '').rstrip('/')}/query_tts_model"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=1.5)) as client:
            response = await client.get(model_url)
            if response.status_code == 405:
                response = await client.post(model_url)
        response.raise_for_status()
    except Exception as exc:
        health.setdefault("detail", {})
        health["models"] = []
        health["model_status"] = "unavailable"
        health["model_error"] = str(exc)
        return health
    payload = response.json() if response.headers.get("content-type", "").lower().startswith("application/json") else {}
    health["model_status"] = "available"
    health["models"] = _extract_tts_models(payload)
    health.setdefault("detail", {})
    health["detail"]["query_tts_model"] = payload
    return health


def _extract_tts_models(payload: dict[str, Any]) -> list[str]:
    for key in ("models", "tts_models", "tts_model_names", "tts_model_name", "model_names", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            models: list[str] = []
            for item in value:
                if isinstance(item, str):
                    models.append(item)
                elif isinstance(item, dict):
                    model_name = str(item.get("name") or item.get("model") or item.get("model_name") or "").strip()
                    if model_name:
                        models.append(model_name)
            return models
        if isinstance(value, dict):
            models = _extract_tts_models(value)
            if models:
                return models
        if isinstance(value, str):
            return [value]
    if isinstance(payload.get("model"), str):
        return [str(payload["model"])]
    return []


async def _probe_avatar_service(base_url: str) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    base = str(base_url or "").rstrip("/")
    for path in ("/easy/query?code=healthcheck", "/v1/easy/query?code=healthcheck", "/query?code=healthcheck"):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=1.5)) as client:
                response = await client.get(f"{base}{path}")
            if response.status_code < 500:
                return {"name": "HeyGem Avatar", "base_url": base_url, "status": "online", "checked_at": checked_at}
        except Exception:
            continue
    return {"name": "HeyGem Avatar", "base_url": base_url, "status": "offline", "checked_at": checked_at}


async def _save_upload(upload: UploadFile | None, *, root: Path, fallback_suffix: str) -> Path | None:
    if upload is None:
        return None
    root.mkdir(parents=True, exist_ok=True)
    path = _unique_upload_path(root, _safe_upload_filename(upload.filename, fallback_suffix=fallback_suffix))
    with path.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    if path.stat().st_size <= 0:
        path.unlink(missing_ok=True)
        return None
    return path


def _safe_upload_filename(filename: str | None, *, fallback_suffix: str) -> str:
    raw_name = str(filename or "").strip()
    basename = PureWindowsPath(raw_name).name if raw_name else ""
    basename = Path(basename).name
    suffix = Path(basename).suffix or fallback_suffix
    suffix = _sanitize_upload_suffix(suffix, fallback_suffix=fallback_suffix)
    stem = Path(basename).stem if basename else "upload"
    stem = re.sub(r'[<>:"/\\|?*#\x00-\x1f]+', "_", stem).strip(" ._") or "upload"
    if stem.upper() in _WINDOWS_RESERVED_FILENAMES:
        stem = f"{stem}_file"
    max_stem_length = max(24, 180 - len(suffix))
    return f"{stem[:max_stem_length]}{suffix}"


def _sanitize_upload_suffix(suffix: str, *, fallback_suffix: str) -> str:
    normalized = str(suffix or fallback_suffix or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9.]", "", normalized)
    if not normalized.startswith("."):
        normalized = f".{normalized}" if normalized else str(fallback_suffix or ".bin")
    if normalized in {".", ""}:
        normalized = str(fallback_suffix or ".bin")
    return normalized[:20]


def _unique_upload_path(root: Path, filename: str) -> Path:
    candidate = root / filename
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.stem
    for index in range(2, 100):
        candidate = root / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return root / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _read_response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail") or payload.get("error") or payload
        return str(detail)[:1000]
    except Exception:
        return (response.text or response.reason_phrase or "request failed")[:1000]


def _write_tts_response_audio(response: httpx.Response, *, output_path: Path, sample_rate: int) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = response.json()
        audio_b64 = str(payload.get("audio_base64") or payload.get("audio") or "").strip()
        if not audio_b64:
            raise HTTPException(status_code=502, detail="CosyVoice3 response did not include audio")
        output_path.write_bytes(base64.b64decode(audio_b64))
        return {"format": output_path.suffix.lstrip(".") or "wav", "raw": _compact_json(payload)}

    content = response.content or b""
    if not content:
        raise HTTPException(status_code=502, detail="CosyVoice3 returned empty audio")
    if "audio/wav" in content_type or content.startswith(b"RIFF"):
        output_path.write_bytes(content)
        return {"format": "wav", "sample_rate": sample_rate}

    _write_pcm16_wav(output_path, content, sample_rate=sample_rate)
    return {"format": "wav", "sample_rate": sample_rate, "source_format": content_type or "pcm_s16le"}


def _write_pcm16_wav(path: Path, pcm_bytes: bytes, *, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)


def _compact_json(payload: dict[str, Any]) -> dict[str, Any]:
    compact = dict(payload)
    for key in ("audio", "audio_base64"):
        if key in compact:
            compact[key] = "<omitted>"
    return compact


def _transcript_result_to_payload(result: TranscriptResult) -> dict[str, Any]:
    return {
        "status": "success",
        "provider": result.provider,
        "model": result.model,
        "language": result.language,
        "duration": result.duration,
        "text": "".join(segment.text for segment in result.segments).strip(),
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "speaker": segment.speaker,
            }
            for segment in result.segments
        ],
    }


def _probe_audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            return round(frames / float(rate), 3) if rate > 0 else 0.0
    except Exception:
        return 0.0


def _copy_avatar_result(result: dict[str, Any]) -> Path | None:
    _AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    local_path = ""
    for segment in segments:
        if isinstance(segment, dict) and str(segment.get("status") or "") == "success":
            local_path = str(segment.get("local_result_path") or "")
            if local_path:
                break
    if not local_path:
        return None
    source = Path(local_path)
    if not source.exists():
        return None
    target = _AVATAR_ROOT / f"avatar_{uuid.uuid4().hex[:12]}{source.suffix or '.mp4'}"
    shutil.copy2(source, target)
    return target
