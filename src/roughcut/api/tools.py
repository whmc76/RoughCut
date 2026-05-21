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
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from roughcut.config import DEFAULT_MINIMAX_REASONING_MODEL, DEFAULT_OUTPUT_ROOT, get_settings, uses_codex_auth_helper
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.providers.avatar.heygem import HeyGemAvatarProvider
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
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
_RUN_STORE_ROOT = _TOOLS_ROOT / "runs"
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_TASKS: dict[str, asyncio.Task[None]] = {}
_RUNS_LOADED = False
_RUN_QUEUE_WORKER: asyncio.Task[None] | None = None
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
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
_COSYVOICE3_INSTRUCT_MAX_CHARS = 160
_MIN_TTS_AUDIO_DURATION_SEC = 0.05
_TTS_TEXT_SEGMENT_MAX_CHARS = 2000
_MOSS_TTS_TEXT_SEGMENT_MAX_CHARS = 120
_TTS_TEXT_HARD_BOUNDARY_CHARS = frozenset("。！？!?；;….")
_TTS_TEXT_SOFT_BOUNDARY_CHARS = frozenset("，,、：:")
_MAX_REFERENCE_AUDIO_SEC = 30.0
_MOSS_REFERENCE_AUDIO_MAX_SEC = 10.0
_MOSS_REFERENCE_LONG_SILENCE_SEC = 0.85
_MOSS_REFERENCE_KEEP_SILENCE_SEC = 0.35
_MOSS_TTS_LOCAL_MODES = frozenset({"moss_direct_tts", "moss_voice_clone", "moss_continuation_clone"})
_MOSS_TTS_LOCAL_MODE_ALIASES = {
    "moss_duration_control": "moss_direct_tts",
}
_MIN_DURATION_TEXT_CHARS = 30
_MIN_DURATION_PER_TEXT_CHAR_SEC = 0.18
_MAX_DURATION_VALIDATION_MIN_SEC = 240.0
_MOSS_DURATION_TOKENS_PER_TEXT_CHAR = 3.2
_MOSS_MIN_AUTO_DURATION_TOKENS = 120
_MOSS_MAX_AUTO_DURATION_TOKENS = 1800
_MOSS_DURATION_MAX_NEW_TOKEN_HEADROOM = 120
_MOSS_REQUEST_HEARTBEAT_SECONDS = 15.0
_MOSS_SEGMENT_REQUEST_TIMEOUT_SECONDS = 300.0
_MOSS_SEGMENT_GENERATION_MAX_SECONDS = 240.0
_MOSS_SERVICE_READY_TIMEOUT_SECONDS = 900.0
_MOSS_SERVICE_READY_POLL_SECONDS = 5.0
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
_TTS_ORALIZE_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "short_video": {
        "label": "短视频口播",
        "goal": "把书面内容改成单人短视频旁白，开头直接进入重点，语句短，节奏清楚。",
        "tone": "自然、利落、有一点交流感，但不要营销腔。",
    },
    "warm_explainer": {
        "label": "亲切讲解",
        "goal": "把内容改成像真人解释问题一样的口播，先说结论，再用一两句补充原因。",
        "tone": "亲切、耐心、清楚，允许少量自然连接词。",
    },
    "calm_narration": {
        "label": "沉稳旁白",
        "goal": "把内容改成克制的旁白，保留信息密度，减少口水词。",
        "tone": "稳定、可信、不过度表演。",
    },
    "podcast_dialogue": {
        "label": "播客对谈",
        "goal": "把内容拆成自然对谈，不硬塞寒暄，不新增事实，用主持人推进问题、嘉宾补充观点。",
        "tone": "像真实播客片段，轮次短，接话自然。",
    },
}


@router.get("/status")
async def tools_status() -> dict[str, Any]:
    _ensure_tool_queue_worker()
    settings = get_settings()
    tts_status = await _probe_tts_service(
        base_url=settings.cosyvoice3_tts_api_base_url,
        name="CosyVoice3 TTS",
    )
    cosyvoice3_status = dict(tts_status)
    tts_status["providers"] = {
        "cosyvoice3": cosyvoice3_status,
        "moss_tts_local": await _probe_json_service(
            base_url=settings.moss_tts_local_api_base_url,
            path=settings.moss_tts_local_health_path,
            name="MOSS-TTS Local 1.7B",
        ),
    }
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "tools": {
            "tts": tts_status,
            "asr": await _probe_json_service(
                base_url=settings.local_asr_api_base_url,
                path=settings.local_asr_health_path,
                name=settings.local_asr_display_name or "Local HTTP ASR",
            ),
            "avatar": await _probe_avatar_service(settings.avatar_api_base_url),
        },
    }


@router.post("/tts/oralize")
async def oralize_tts_text(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    source_text = _strip_tts_text_ui_hints(str(payload.get("text") or payload.get("tts_text") or ""))
    if not source_text:
        raise HTTPException(status_code=400, detail="text is required")

    style = _normalize_tts_oralize_style(payload.get("style"))
    provider = str(payload.get("provider") or "moss_tts_local").strip() or "moss_tts_local"
    speaker_count = _clamp_int(payload.get("speaker_count"), default=1, minimum=1, maximum=5)
    target_chars = _clamp_int(payload.get("target_chars"), default=0, minimum=0, maximum=3000)
    prompt_messages = _build_tts_oralization_messages(
        source_text=source_text,
        style=style,
        provider=provider,
        speaker_count=speaker_count,
        target_chars=target_chars,
    )

    try:
        response = await _complete_tts_oralization(prompt_messages)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TTS 口语化改写失败: {exc}") from exc

    try:
        structured_payload = response.as_json()
    except Exception:
        structured_payload = _parse_structured_tts_payload(response.content)
    try:
        tts_text = _resolve_tts_spoken_text(
            json.dumps(structured_payload, ensure_ascii=False) if structured_payload is not None else response.content
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"TTS 口语化结果不可朗读: {exc}") from exc
    if not tts_text:
        raise HTTPException(status_code=502, detail="TTS 口语化改写没有返回 tts_text")

    return {
        "status": "success",
        "provider": provider,
        "style": style,
        "style_label": _TTS_ORALIZE_STYLE_PRESETS[style]["label"],
        "speaker_count": speaker_count,
        "tts_text": tts_text,
        "structured_payload": structured_payload,
        "model": response.model,
        "usage": response.usage,
    }


async def _complete_tts_oralization(prompt_messages: list[Message]):
    settings = get_settings()
    openai_key = str(getattr(settings, "openai_api_key", "") or "").strip()
    uses_codex_bridge = uses_codex_auth_helper(settings) and not openai_key
    if uses_codex_bridge:
        minimax_key = str(getattr(settings, "minimax_api_key", "") or "").strip()
        if not minimax_key:
            raise RuntimeError("口语化改写需要可直接调用的轻量文案模型；当前只有 Codex bridge，短文本改写不再使用 Codex agent")
        from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider

        return await MiniMaxReasoningProvider(model=DEFAULT_MINIMAX_REASONING_MODEL).complete(
            prompt_messages,
            temperature=0.35,
            max_tokens=1800,
            json_mode=True,
        )
    return await get_reasoning_provider().complete(
        prompt_messages,
        temperature=0.35,
        max_tokens=1800,
        json_mode=True,
    )


@router.post("/tts")
async def run_tts(
    provider: str = Form(default="cosyvoice3"),
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
    moss_duration_tokens: int = Form(default=0),
    moss_max_new_tokens: int = Form(default=0),
    moss_temperature: float = Form(default=1.1),
    moss_top_p: float = Form(default=0.9),
    moss_top_k: int = Form(default=50),
    moss_repetition_penalty: float = Form(default=1.1),
    auto_prompt_text_asr: bool = Form(default=True),
    reference_history_path: str = Form(default=""),
    reference_audio: UploadFile | None = File(default=None),
    prompt_wav: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    _ensure_tool_queue_worker()
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
    if reference_path is not None and not str(prompt_text or "").strip():
        prompt_text = _read_reference_audio_prompt_text(reference_path)
    request = {
        "text": normalized_text,
        "original_text": normalized_text,
        "provider": provider,
        "mode": mode,
        "prompt_text": prompt_text,
        "instruct_text": instruct_text,
        "spk_id": spk_id,
        "zero_shot_spk_id": zero_shot_spk_id,
        "stream": stream,
        "speed": speed,
        "seed": seed,
        "text_frontend": text_frontend,
        "moss_duration_tokens": moss_duration_tokens,
        "moss_max_new_tokens": moss_max_new_tokens,
        "moss_temperature": moss_temperature,
        "moss_top_p": moss_top_p,
        "moss_top_k": moss_top_k,
        "moss_repetition_penalty": moss_repetition_penalty,
        "auto_prompt_text_asr": auto_prompt_text_asr,
        "reference_path": str(reference_path) if reference_path is not None else None,
    }
    run = _create_run("tts", request=request)
    _update_run_stage(run["run_id"], "upload", detail="TTS request accepted")
    _enqueue_run(run["run_id"])
    return _run_public_payload(run)


@router.get("/tts/reference-audio")
async def list_tts_reference_audio() -> dict[str, Any]:
    _ensure_tool_queue_worker()
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": _list_reference_audio_history(),
    }


@router.get("/tts/outputs")
async def list_tts_outputs() -> dict[str, Any]:
    _ensure_tool_queue_worker()
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
    _ensure_tool_queue_worker()
    audio_path = await _save_upload(audio, root=_ASR_UPLOAD_ROOT, fallback_suffix=".wav")
    if audio_path is None:
        raise HTTPException(status_code=400, detail="audio is required")

    run = _create_run("asr", request={
        "audio_path": str(audio_path),
        "language": language or "zh-CN",
        "prompt": prompt or "",
    })
    _update_run_stage(run["run_id"], "upload", detail="ASR audio uploaded", progress=0.04, path=str(audio_path))
    _enqueue_run(run["run_id"])
    return _run_public_payload(run)


@router.post("/avatar")
async def run_avatar(
    script: str = Form(default=""),
    presenter_video: UploadFile = File(...),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    _ensure_tool_queue_worker()
    presenter_path = await _save_upload(presenter_video, root=_UPLOAD_ROOT, fallback_suffix=".mp4")
    audio_path = await _save_upload(audio, root=_UPLOAD_ROOT, fallback_suffix=".wav")
    if presenter_path is None or audio_path is None:
        raise HTTPException(status_code=400, detail="presenter_video and audio are required")

    run = _create_run("avatar", request={
        "script": script,
        "presenter_path": str(presenter_path),
        "audio_path": str(audio_path),
    })
    _update_run_stage(
        run["run_id"],
        "upload",
        detail="Avatar source media uploaded",
        progress=0.04,
        presenter_path=str(presenter_path),
        audio_path=str(audio_path),
    )
    _enqueue_run(run["run_id"])
    return _run_public_payload(run)


@router.get("/runs/{run_id}")
async def get_tool_run(run_id: str) -> dict[str, Any]:
    _ensure_tool_queue_worker()
    run = _RUNS.get(str(run_id or "").strip())
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_public_payload(run)


async def _execute_tts_run(
    run_id: str,
    *,
    text: str,
    original_text: str,
    provider: str,
    mode: str,
    prompt_text: str,
    instruct_text: str,
    spk_id: str,
    zero_shot_spk_id: str,
    stream: bool,
    speed: float,
    seed: int,
    text_frontend: bool,
    moss_duration_tokens: int,
    moss_max_new_tokens: int,
    moss_temperature: float,
    moss_top_p: float,
    moss_top_k: int,
    moss_repetition_penalty: float,
    auto_prompt_text_asr: bool,
    reference_path: Path | None,
) -> None:
    settings = get_settings()
    _TTS_ROOT.mkdir(parents=True, exist_ok=True)
    resolved_provider = str(provider or "cosyvoice3").strip().lower().replace("-", "_")
    requested_mode = str(mode or "").strip().lower()
    if requested_mode.startswith("moss_") and resolved_provider in {"", "cosyvoice3", "cosyvoice"}:
        resolved_provider = "moss_tts_local"
    if resolved_provider in {"moss", "moss_local", "moss_tts", "moss_tts_family", "moss_tts_local", "moss_tts_local_transformer"}:
        await _execute_moss_tts_local_run(
            run_id,
            text=text,
            original_text=original_text,
            prompt_text=prompt_text,
            mode=mode,
            duration_tokens=moss_duration_tokens,
            max_new_tokens=moss_max_new_tokens,
            temperature=moss_temperature,
            top_p=moss_top_p,
            top_k=moss_top_k,
            repetition_penalty=moss_repetition_penalty,
            seed=seed,
            auto_prompt_text_asr=auto_prompt_text_asr,
            reference_path=reference_path,
        )
        return
    if resolved_provider not in {"", "cosyvoice3", "cosyvoice"}:
        raise RuntimeError(f"Unsupported TTS provider: {provider}")
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
    source_reference_path = reference_path
    if reference_path is not None:
        reference_path = _prepare_reference_audio_for_cosyvoice(reference_path, run_id=run_id)
    prompt_text_source = "manual" if str(prompt_text or "").strip() else ""
    user_prompt_text = _strip_cosyvoice_prompt_boundary(prompt_text)
    if resolved_mode == "zero_shot":
        user_prompt_text, prompt_text_source = await _resolve_prompt_text_for_prepared_reference(
            run_id,
            source_reference_path=source_reference_path,
            reference_path=reference_path,
            prompt_text=user_prompt_text,
            enabled=auto_prompt_text_asr,
            provider_label="CosyVoice3",
        )
    if source_reference_path is not None and user_prompt_text:
        _write_reference_audio_metadata(
            source_reference_path,
            prompt_text=user_prompt_text,
            prompt_text_source=prompt_text_source,
            provider="cosyvoice3",
            mode=resolved_mode,
        )
    resolved_prompt_text = _normalize_cosyvoice3_prompt_text(user_prompt_text) if resolved_mode == "zero_shot" else user_prompt_text
    user_instruct_text = _strip_cosyvoice_prompt_boundary(instruct_text)
    effective_instruct_text = _compact_cosyvoice3_instruct_text(user_instruct_text) if resolved_mode in {"instruct", "instruct2"} else user_instruct_text
    resolved_instruct_text = _normalize_cosyvoice3_instruct_text(effective_instruct_text) if resolved_mode in {"instruct", "instruct2"} else effective_instruct_text
    if resolved_mode == "zero_shot" and not user_prompt_text:
        raise RuntimeError("CosyVoice3 zero_shot TTS requires prompt_text")
    if resolved_mode in {"instruct", "instruct2"} and not effective_instruct_text:
        raise RuntimeError("CosyVoice3 instruct2 TTS requires instruct_text")
    polluted_fragments = [fragment for fragment in (user_prompt_text, effective_instruct_text) if fragment and fragment in text]
    if polluted_fragments:
        raise RuntimeError("朗读正文包含参考文本或口播指令；请保持 tts_text 只包含实际需要说出口的正文")
    if resolved_mode == "sft" and not str(spk_id or "").strip():
        raise RuntimeError("CosyVoice3 sft TTS requires spk_id from /query_tts_model")
    if stream and abs(float(speed or 1.0) - 1.0) > 0.0001:
        raise RuntimeError("CosyVoice3 streaming mode requires speed=1; use stream=false for speed changes")
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

    created_at = datetime.now(timezone.utc)
    output_path = _unique_upload_path(
        _TTS_ROOT,
        _build_tts_output_filename(
            created_at=created_at,
            mode=resolved_mode,
            prompt_text=user_prompt_text,
            instruct_text=effective_instruct_text,
            spk_id=spk_id,
            zero_shot_spk_id=zero_shot_spk_id,
            stream=stream,
            speed=float(speed or 1.0),
            seed=int(seed or 0),
            text_frontend=text_frontend,
            reference_path=source_reference_path,
            segment_count=len(text_segments),
        ),
    )
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
    result = {
        "status": "success",
        "provider": "official-cosyvoice3",
        "mode": resolved_mode,
        "created_at": created_at.isoformat(),
        "display_name": output_path.name,
        "config_summary": _tts_output_config_summary(
            mode=resolved_mode,
            prompt_text=user_prompt_text,
            instruct_text=effective_instruct_text,
            spk_id=spk_id,
            zero_shot_spk_id=zero_shot_spk_id,
            stream=stream,
            speed=float(speed or 1.0),
            seed=int(seed or 0),
            text_frontend=text_frontend,
            reference_path=source_reference_path,
            segment_count=len(text_segments),
        ),
        "text": text,
        "tts_text": text,
        "original_text": original_text,
        "prompt_text": user_prompt_text,
        "prompt_text_source": prompt_text_source,
        "instruct_text": effective_instruct_text,
        "raw_instruct_text": user_instruct_text if user_instruct_text != effective_instruct_text else "",
        "reference_audio": str(source_reference_path) if source_reference_path is not None else None,
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
    }
    _write_tts_output_metadata(output_path, result)
    _complete_run(run_id, result)


async def _execute_moss_tts_local_run(
    run_id: str,
    *,
    text: str,
    original_text: str,
    prompt_text: str,
    mode: str,
    duration_tokens: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    seed: int,
    auto_prompt_text_asr: bool,
    reference_path: Path | None,
) -> None:
    settings = get_settings()
    resolved_mode = _normalize_moss_tts_local_mode(mode)
    if resolved_mode not in _MOSS_TTS_LOCAL_MODES:
        raise RuntimeError(f"Unsupported MOSS-TTS Local mode: {mode}")
    requested_duration_tokens = max(0, int(duration_tokens or 0))
    requires_reference = resolved_mode in {"moss_voice_clone", "moss_continuation_clone"}
    requires_prompt_text = resolved_mode == "moss_continuation_clone"
    if requires_reference and reference_path is None:
        raise RuntimeError("MOSS-TTS Local voice clone requires prompt_wav/reference_audio")
    user_prompt_text = str(prompt_text or "").strip()
    prompt_text_source = "manual" if user_prompt_text else ""
    source_reference_path = reference_path if requires_reference else None
    if source_reference_path is not None:
        reference_path = _prepare_reference_audio_for_moss(source_reference_path, run_id=run_id)
    else:
        reference_path = None
    if requires_prompt_text:
        user_prompt_text, prompt_text_source = await _resolve_prompt_text_for_prepared_reference(
            run_id,
            source_reference_path=source_reference_path,
            reference_path=reference_path,
            prompt_text=user_prompt_text,
            enabled=auto_prompt_text_asr,
            provider_label="MOSS-TTS Local",
        )
        if not user_prompt_text:
            raise RuntimeError("MOSS-TTS Local continuation requires prompt_text for the reference audio")
    if source_reference_path is not None and user_prompt_text:
        _write_reference_audio_metadata(
            source_reference_path,
            prompt_text=user_prompt_text,
            prompt_text_source=prompt_text_source,
            provider="moss_tts_local",
            mode=resolved_mode,
        )
    _update_run_stage(
        run_id,
        "validate",
        detail="Validated MOSS-TTS Local form fields",
        provider="moss_tts_local",
        mode=resolved_mode,
        reference_audio=source_reference_path is not None,
        duration_tokens=requested_duration_tokens,
    )

    text_segments = _split_tts_text_for_synthesis(text, max_chars=_MOSS_TTS_TEXT_SEGMENT_MAX_CHARS)
    if not text_segments:
        raise RuntimeError("text is required")

    endpoint = "/inference"
    sample_rate = int(settings.moss_tts_local_sample_rate or 24000)
    segment_output_paths: list[Path] = []
    response: httpx.Response | None = None
    segment_duration_tokens = [
        _resolve_moss_segment_duration_tokens(
            segment_text,
            requested_duration_tokens=requested_duration_tokens,
            total_text=text,
            segment_count=len(text_segments),
        )
        for segment_text in text_segments
    ]
    segment_max_new_tokens = [
        _resolve_moss_segment_max_new_tokens(
            segment_text,
            requested_max_new_tokens=max_new_tokens,
            duration_tokens=segment_duration_tokens[index],
        )
        for index, segment_text in enumerate(text_segments)
    ]

    try:
        _update_run_stage(run_id, "service_start", detail="Starting MOSS-TTS Local service")
        async with hold_managed_gpu_services_async(
            required_urls=[settings.moss_tts_local_api_base_url],
            reason="tools_tts_moss_local",
        ):
            await _wait_moss_tts_local_ready(run_id, settings)
            _update_run_stage(
                run_id,
                "request",
                detail=(
                    "Submitting MOSS-TTS Local request"
                    if len(text_segments) == 1
                    else f"Submitting MOSS-TTS Local request 1/{len(text_segments)}"
                ),
                endpoint=endpoint,
                mode=resolved_mode,
                segment_count=len(text_segments),
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=20.0), follow_redirects=True) as client:
                for index, segment_text in enumerate(text_segments, start=1):
                    if len(text_segments) > 1:
                        _update_run_stage(
                            run_id,
                            "request",
                            detail=f"Submitting MOSS-TTS Local request {index}/{len(text_segments)}",
                            progress=0.34 + ((index - 1) / max(len(text_segments), 1)) * 0.36,
                            endpoint=endpoint,
                            mode=resolved_mode,
                            segment_index=index,
                            segment_count=len(text_segments),
                        )
                    data = _build_moss_tts_local_form_data(
                        text=segment_text,
                        mode=resolved_mode,
                        prompt_text=user_prompt_text,
                        duration_tokens=segment_duration_tokens[index - 1],
                        max_new_tokens=segment_max_new_tokens[index - 1],
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        repetition_penalty=repetition_penalty,
                        seed=seed,
                    )
                    response = await _post_moss_tts_segment_request_with_progress(
                        run_id,
                        client,
                        f"{settings.moss_tts_local_api_base_url.rstrip('/')}{endpoint}",
                        data=data,
                        reference_path=reference_path,
                        segment_index=index,
                        segment_count=len(text_segments),
                        max_new_tokens=segment_max_new_tokens[index - 1],
                    )
                    response.raise_for_status()
                    if len(text_segments) > 1:
                        _update_run_stage(
                            run_id,
                            "process",
                            detail=f"MOSS-TTS Local response received {index}/{len(text_segments)}",
                            progress=0.55 + (index / max(len(text_segments), 1)) * 0.24,
                            segment_index=index,
                            segment_count=len(text_segments),
                        )
                        segment_path = _TTS_ROOT / f"tts_{run_id}_{index:03d}.segment.wav"
                        _write_tts_response_audio(response, output_path=segment_path, sample_rate=sample_rate)
                        segment_duration = _validate_tts_audio_output(segment_path, service_label="MOSS-TTS Local", segment_index=index)
                        _validate_tts_audio_duration_for_text(
                            segment_duration,
                            segment_text,
                            service_label="MOSS-TTS Local",
                            segment_index=index,
                        )
                        segment_output_paths.append(segment_path)
        _update_run_stage(run_id, "process", detail="MOSS-TTS Local response received")
    except httpx.HTTPStatusError as exc:
        _cleanup_paths(segment_output_paths)
        detail = _read_response_error(exc.response)
        raise RuntimeError(f"MOSS-TTS Local failed: {detail}") from exc
    except Exception as exc:
        _cleanup_paths(segment_output_paths)
        raise RuntimeError(f"MOSS-TTS Local unavailable: {exc}") from exc

    created_at = datetime.now(timezone.utc)
    output_path = _unique_upload_path(
        _TTS_ROOT,
        _build_tts_output_filename(
            created_at=created_at,
            mode="moss-local-voice-clone" if requires_reference else "moss-local-direct",
            prompt_text=user_prompt_text,
            instruct_text="",
            spk_id="",
            zero_shot_spk_id="",
            stream=False,
            speed=1.0,
            seed=int(seed or 0),
            text_frontend=True,
            reference_path=source_reference_path,
            segment_count=len(text_segments),
        ),
    )
    _update_run_stage(run_id, "write_artifact", detail="Writing synthesized audio", output_path=str(output_path))
    try:
        if len(text_segments) == 1:
            if response is None:
                raise RuntimeError("MOSS-TTS Local did not return a response")
            meta = _write_tts_response_audio(response, output_path=output_path, sample_rate=sample_rate)
            meta["duration"] = _validate_tts_audio_output(output_path, service_label="MOSS-TTS Local")
        else:
            meta = _concatenate_tts_wav_segments(segment_output_paths, output_path=output_path)
            meta["duration"] = _validate_tts_audio_output(output_path, service_label="MOSS-TTS Local")
        _validate_tts_audio_duration_for_text(
            float(meta.get("duration") or 0.0),
            text,
            service_label="MOSS-TTS Local",
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        _cleanup_paths(segment_output_paths)

    sampling_params = {
        "max_new_tokens": max(segment_max_new_tokens),
        "audio_temperature": max(0.0, float(temperature if temperature is not None else 1.0)),
        "audio_top_p": min(1.0, max(0.01, float(top_p if top_p is not None else 0.95))),
        "audio_top_k": max(1, int(top_k or 50)),
        "audio_repetition_penalty": max(0.01, float(repetition_penalty if repetition_penalty is not None else 1.1)),
        "seed": max(0, int(seed or 0)),
    }
    result = {
        "status": "success",
        "provider": "official-moss-tts-local",
        "mode": resolved_mode,
        "created_at": created_at.isoformat(),
        "display_name": output_path.name,
        "config_summary": _moss_tts_output_config_summary(
            mode=resolved_mode,
            prompt_text=user_prompt_text,
            reference_path=source_reference_path,
            duration_tokens=requested_duration_tokens,
            segment_duration_tokens=segment_duration_tokens,
            sampling_params=sampling_params,
            segment_count=len(text_segments),
        ),
        "text": text,
        "tts_text": text,
        "original_text": original_text,
        "prompt_text": user_prompt_text,
        "prompt_text_source": prompt_text_source,
        "reference_audio": str(source_reference_path) if source_reference_path is not None else None,
        "output_path": str(output_path),
        "audio_url": f"/api/v1/tools/artifacts/tts/{output_path.name}",
        "segment_count": len(text_segments),
        "text_segments": [
            {
                "index": index,
                "text": segment_text,
                "char_count": _moss_tts_text_char_count(segment_text),
                "duration_tokens": segment_duration_tokens[index - 1],
                "max_new_tokens": segment_max_new_tokens[index - 1],
            }
            for index, segment_text in enumerate(text_segments, start=1)
        ],
        "moss_duration_tokens": requested_duration_tokens,
        "moss_segment_duration_tokens": segment_duration_tokens,
        "sampling_params": sampling_params,
        **meta,
    }
    _write_tts_output_metadata(output_path, result)
    _complete_run(run_id, result)


def _build_tts_segment_form_data(base_data: dict[str, str], text: str) -> dict[str, str]:
    data = dict(base_data)
    data["tts_text"] = text
    data["text"] = text
    return data


def _build_moss_tts_local_form_data(
    *,
    text: str,
    mode: str,
    prompt_text: str,
    duration_tokens: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    seed: int,
) -> dict[str, str]:
    resolved_mode = _normalize_moss_tts_local_mode(mode)
    resolved_seed = max(0, int(seed or 0))
    return {
        "mode": resolved_mode,
        "tts_text": str(text or ""),
        "text": str(text or ""),
        "prompt_text": str(prompt_text or ""),
        "continuation": "true" if resolved_mode == "moss_continuation_clone" else "false",
        "duration_tokens": str(max(0, int(duration_tokens or 0))),
        "max_new_tokens": str(max(1, int(max_new_tokens or 2048))),
        "audio_temperature": str(max(0.0, float(temperature if temperature is not None else 1.0))),
        "audio_top_p": str(min(1.0, max(0.01, float(top_p if top_p is not None else 0.95)))),
        "audio_top_k": str(max(1, int(top_k or 50))),
        "audio_repetition_penalty": str(max(0.01, float(repetition_penalty if repetition_penalty is not None else 1.1))),
        "seed": str(resolved_seed),
        "max_generation_seconds": _format_config_number(_MOSS_SEGMENT_GENERATION_MAX_SECONDS),
    }


async def _post_moss_tts_segment_request_with_progress(
    run_id: str,
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict[str, str],
    reference_path: Path | None,
    segment_index: int,
    segment_count: int,
    max_new_tokens: int,
) -> httpx.Response:
    started_at = datetime.now(timezone.utc)
    task = asyncio.create_task(
        _post_tts_segment_request(
            client,
            url,
            data=data,
            reference_path=reference_path,
        )
    )
    segment_total = max(1, int(segment_count or 1))
    segment_position = max(1, min(segment_total, int(segment_index or 1)))
    request_span = 0.36 / segment_total
    progress_floor = 0.34 + (segment_position - 1) * request_span
    progress_ceiling = min(0.54, progress_floor + max(0.04, request_span * 0.92))
    estimated_seconds = max(45.0, min(240.0, int(max_new_tokens or 0) / 8.0))
    try:
        while True:
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed > _MOSS_SEGMENT_REQUEST_TIMEOUT_SECONDS:
                if not task.done():
                    task.cancel()
                raise RuntimeError(
                    "MOSS-TTS Local segment timed out after "
                    f"{int(_MOSS_SEGMENT_REQUEST_TIMEOUT_SECONDS)}s; "
                    "try shorter text, direct TTS, or restart the MOSS-TTS service if prior requests are still running"
                )
            done, _ = await asyncio.wait({task}, timeout=_MOSS_REQUEST_HEARTBEAT_SECONDS)
            if done:
                return task.result()
            progress_ratio = min(0.95, elapsed / estimated_seconds)
            progress = progress_floor + (progress_ceiling - progress_floor) * progress_ratio
            detail = (
                f"MOSS-TTS Local generating request {segment_position}/{segment_total} "
                f"({int(elapsed)}s elapsed)"
            )
            _update_run_stage(
                run_id,
                "request",
                detail=detail,
                progress=progress,
                segment_index=segment_position,
                segment_count=segment_total,
                max_new_tokens=int(max_new_tokens or 0),
                elapsed_seconds=int(elapsed),
            )
    except Exception:
        if not task.done():
            task.cancel()
        raise


def _normalize_moss_tts_local_mode(mode: object) -> str:
    requested = str(mode or "moss_voice_clone").strip().lower()
    return _MOSS_TTS_LOCAL_MODE_ALIASES.get(requested, requested)


async def _wait_moss_tts_local_ready(run_id: str, settings: Any) -> None:
    base_url = str(settings.moss_tts_local_api_base_url or "").rstrip("/")
    health_path = str(settings.moss_tts_local_health_path or "/health")
    url = f"{base_url}{health_path if health_path.startswith('/') else f'/{health_path}'}"
    started_at = datetime.now(timezone.utc)
    last_error = ""
    while True:
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        if elapsed > _MOSS_SERVICE_READY_TIMEOUT_SECONDS:
            raise RuntimeError(f"MOSS-TTS Local did not become ready after {int(elapsed)}s: {last_error or 'not ready'}")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=2.0), follow_redirects=True) as client:
                response = await client.get(url)
            payload = response.json() if response.headers.get("content-type", "").lower().startswith("application/json") else {}
            if response.status_code < 400 and not bool(payload.get("busy")):
                return
            if response.status_code < 400 and bool(payload.get("busy")):
                active = payload.get("active_inference") if isinstance(payload, dict) else None
                last_error = f"service busy: {active or {}}"
            else:
                last_error = f"HTTP {response.status_code}: {_read_response_error(response)}"
        except Exception as exc:
            last_error = str(exc)
        _update_run_stage(
            run_id,
            "service_start",
            detail=f"Waiting for MOSS-TTS Local to become ready ({int(elapsed)}s)",
            progress=0.18,
            service_error=last_error,
        )
        await asyncio.sleep(_MOSS_SERVICE_READY_POLL_SECONDS)


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _resolve_moss_segment_duration_tokens(
    text: str,
    *,
    requested_duration_tokens: int,
    total_text: str,
    segment_count: int,
) -> int:
    requested = int(requested_duration_tokens or 0)
    if requested > 0:
        if int(segment_count or 1) <= 1:
            return requested
        total_chars = max(1, _moss_tts_text_char_count(total_text))
        segment_chars = max(1, _moss_tts_text_char_count(text))
        return max(1, int(round(requested * segment_chars / total_chars)))
    text_chars = _moss_tts_text_char_count(text)
    if text_chars <= 0:
        return 0
    return min(
        _MOSS_MAX_AUTO_DURATION_TOKENS,
        max(_MOSS_MIN_AUTO_DURATION_TOKENS, int(round(text_chars * _MOSS_DURATION_TOKENS_PER_TEXT_CHAR))),
    )


def _resolve_moss_segment_max_new_tokens(
    text: str,
    *,
    requested_max_new_tokens: int,
    duration_tokens: int,
) -> int:
    duration_token_count = int(duration_tokens or 0)
    if duration_token_count > 0:
        token_budget = duration_token_count + _MOSS_DURATION_MAX_NEW_TOKEN_HEADROOM
        requested = int(requested_max_new_tokens or 0)
        if requested > 0:
            token_budget = min(token_budget, max(duration_token_count, requested))
        return max(duration_token_count, token_budget, 128)
    compact_len = _moss_tts_text_char_count(text)
    estimated_seconds = max(4.0, compact_len / 4.0 + 3.0)
    estimated_tokens = int(estimated_seconds * 12.5 * 1.35)
    return max(256, min(4096, max(int(requested_max_new_tokens or 0), estimated_tokens)))


def _moss_tts_text_char_count(text: str) -> int:
    cleaned = re.sub(r"\[S[1-5]\]|\$\{[^}]+\}", "", str(text or ""))
    return len(re.sub(r"\s+", "", cleaned))


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


def _trim_trailing_tts_silence(path: Path, *, threshold: str = "-45dB", min_silence: float = 0.8) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not path.exists() or path.stat().st_size <= 0:
        return False
    temp_path = path.with_name(f"{path.stem}.trimmed{path.suffix}")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-af",
        f"silenceremove=stop_periods=-1:stop_duration={float(min_silence):.2f}:stop_threshold={threshold}",
        "-c:a",
        "pcm_s16le",
        str(temp_path),
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    except (OSError, subprocess.SubprocessError):
        temp_path.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size <= 44:
        temp_path.unlink(missing_ok=True)
        return False
    try:
        if (_audio_duration_seconds(temp_path) or 0) <= 0:
            temp_path.unlink(missing_ok=True)
            return False
        temp_path.replace(path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        return False
    return True


def _strip_cosyvoice_prompt_boundary(value: str | None) -> str:
    cleaned = str(value or "").replace(_COSYVOICE3_END_OF_PROMPT, "").strip()
    if cleaned.startswith(_COSYVOICE3_SYSTEM_PROMPT):
        cleaned = cleaned[len(_COSYVOICE3_SYSTEM_PROMPT):].strip()
    return cleaned


def _strip_tts_text_ui_hints(value: str | None) -> str:
    return _collapse_tts_text(_remove_tts_text_ui_hints(value))


def _normalize_tts_oralize_style(value: Any) -> str:
    style = str(value or "").strip()
    return style if style in _TTS_ORALIZE_STYLE_PRESETS else "short_video"


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _build_tts_oralization_messages(
    *,
    source_text: str,
    style: str,
    provider: str,
    speaker_count: int,
    target_chars: int,
) -> list[Message]:
    style_config = _TTS_ORALIZE_STYLE_PRESETS[_normalize_tts_oralize_style(style)]
    speaker_rule = (
        "如果 speaker_count 大于 1，tts_text 必须使用 [S1]-[S5] 标签；每轮只写一句自然接话。"
        if speaker_count > 1
        else "单人口播不要加 [S1] 标签，除非输入原文已经显式包含说话人标签。"
    )
    length_rule = f"目标长度约 {target_chars} 个中文字；如果原文更短，不要硬扩写。" if target_chars > 0 else "长度以信息完整为准，不要为了口语化灌水。"
    system_prompt = (
        "你是中文 TTS 口播改写器。你的任务是把书面文本改成真实人会说出口的配音稿，"
        "不是写创作提示词，也不是增加背景设定。只输出 JSON。"
    )
    user_prompt = {
        "task": "rewrite_for_natural_tts",
        "provider": provider,
        "style": {
            "key": style,
            "label": style_config["label"],
            "goal": style_config["goal"],
            "tone": style_config["tone"],
        },
        "speaker_count": speaker_count,
        "rules": [
            "只改写表达方式，不能新增事实、数据、品牌、人物或结论。",
            "保留专有名词、数字、时间、金额、型号和关键判断。",
            "把长句拆短，优先使用自然停顿和中文标点帮助 TTS 呼吸。",
            "去掉书面化连接词、列表腔、AI 总结腔和过度宣传腔。",
            "可以少量加入“其实、你会发现、先说结论、说白了”这类口语连接，但不要每句都加。",
            "不要输出舞台指令、括号情绪、音效提示、Markdown 或解释文字。",
            speaker_rule,
            length_rule,
        ],
        "output_schema": {
            "tts_text": "最终送入 TTS 的可朗读正文。",
            "voiceover_segments": [
                {
                    "purpose": "hook | point | transition | close",
                    "source_text": "对应原文片段",
                    "rewritten_text": "该片段的可朗读改写",
                }
            ],
            "delivery_notes": {
                "pace": "语速建议",
                "pause": "停顿建议",
                "emphasis": ["需要自然强调的词"],
            },
        },
        "source_text": source_text,
    }
    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=json.dumps(user_prompt, ensure_ascii=False)),
    ]


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
    body = _compact_cosyvoice3_instruct_text(value)
    if not body:
        return ""
    if body.startswith(_COSYVOICE3_SYSTEM_PROMPT):
        body = body[len(_COSYVOICE3_SYSTEM_PROMPT):].strip()
    return f"{_COSYVOICE3_SYSTEM_PROMPT}\n{body}{_COSYVOICE3_END_OF_PROMPT}"


def _compact_cosyvoice3_instruct_text(value: str) -> str:
    body = _strip_cosyvoice_prompt_boundary(value)
    if not body:
        return ""
    for separator in ("；", ";"):
        body = body.replace(separator, "\n")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    compact_lines: list[str] = []
    seen: set[str] = set()
    for line in lines or [body.strip()]:
        compact_line = _normalize_cosyvoice3_instruct_line(line)
        if not compact_line or compact_line in seen:
            continue
        candidate = "；".join([*compact_lines, compact_line])
        if len(candidate) > _COSYVOICE3_INSTRUCT_MAX_CHARS:
            break
        compact_lines.append(compact_line)
        seen.add(compact_line)
    compact = "；".join(compact_lines)
    if len(compact) > _COSYVOICE3_INSTRUCT_MAX_CHARS:
        compact = _truncate_cosyvoice3_instruct_line(compact, max_chars=_COSYVOICE3_INSTRUCT_MAX_CHARS)
    return _ensure_sentence_punctuation(compact)


def _normalize_cosyvoice3_instruct_line(value: str) -> str:
    line = _strip_wrapping_quotes(value)
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
    line = line.strip(" ，,。.")
    return line


def _truncate_cosyvoice3_instruct_line(value: str, *, max_chars: int) -> str:
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


async def _resolve_reference_prompt_text_from_asr(
    run_id: str,
    *,
    reference_path: Path | None,
    enabled: bool,
    provider_label: str,
) -> tuple[str, str]:
    if reference_path is None:
        return "", ""
    if not enabled:
        return "", ""
    provider = LocalHTTPASRProvider()

    def on_progress(payload: dict[str, Any]) -> None:
        provider_progress = _coerce_progress(payload.get("progress"))
        mapped_progress = None if provider_progress is None else 0.10 + (provider_progress * 0.16)
        phase = str(payload.get("phase") or "process").strip()
        _update_run_stage(
            run_id,
            "process",
            detail=str(payload.get("detail") or f"Reference ASR {phase}"),
            progress=mapped_progress,
            provider_progress=provider_progress,
            provider_phase=phase,
            provider_payload=_compact_progress_payload(payload),
        )

    try:
        settings = get_settings()
        _update_run_stage(run_id, "service_start", detail=f"Starting ASR for {provider_label} reference text")
        async with hold_managed_gpu_services_async(
            required_urls=[settings.local_asr_api_base_url],
            reason="tools_tts_reference_prompt_asr",
        ):
            _update_run_stage(run_id, "request", detail="Recognizing reference audio prompt_text with ASR")
            result = await provider.transcribe(
                reference_path,
                language="zh-CN",
                prompt=None,
                progress_callback=on_progress,
            )
    except Exception as exc:
        raise RuntimeError(f"{provider_label} reference prompt_text ASR failed: {exc}") from exc
    text = _transcript_result_text(result)
    if not text:
        raise RuntimeError(f"{provider_label} reference prompt_text ASR returned empty text")
    return text, "auto_asr"


async def _resolve_prompt_text_for_prepared_reference(
    run_id: str,
    *,
    source_reference_path: Path | None,
    reference_path: Path | None,
    prompt_text: str,
    enabled: bool,
    provider_label: str,
) -> tuple[str, str]:
    user_prompt_text = str(prompt_text or "").strip()
    prompt_text_source = "manual" if user_prompt_text else ""
    if _reference_audio_needs_prompt_text_calibration(source_reference_path, reference_path):
        _update_run_stage(
            run_id,
            "validate",
            detail=f"{provider_label} 参考音频已被裁剪或压缩，正在重新识别实际送入服务的 prompt_text",
            reference_source=str(source_reference_path or ""),
            reference_output=str(reference_path or ""),
        )
        try:
            user_prompt_text, _ = await _resolve_reference_prompt_text_from_asr(
                run_id,
                reference_path=reference_path,
                enabled=True,
                provider_label=provider_label,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{provider_label} 参考音频被裁剪或压缩后，prompt_text 必须匹配实际送入服务的音频；"
                f"自动校准参考文本失败：{exc}"
            ) from exc
        return user_prompt_text, "auto_asr_prepared_reference"
    if not user_prompt_text:
        return await _resolve_reference_prompt_text_from_asr(
            run_id,
            reference_path=reference_path,
            enabled=enabled,
            provider_label=provider_label,
        )
    return user_prompt_text, prompt_text_source


def _reference_audio_needs_prompt_text_calibration(source_reference_path: Path | None, reference_path: Path | None) -> bool:
    if source_reference_path is None or reference_path is None:
        return False
    try:
        if source_reference_path.resolve() == reference_path.resolve():
            return False
    except OSError:
        return False
    return True


def _transcript_result_text(result: Any) -> str:
    direct_text = str(getattr(result, "text", "") or "").strip()
    if direct_text:
        return direct_text
    segments = getattr(result, "segments", None)
    if isinstance(segments, list):
        return _collapse_tts_text("\n".join(str(getattr(segment, "text", "") or "") for segment in segments))
    return ""


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


def _enqueue_run(run_id: str) -> None:
    run = _RUNS.get(run_id)
    if run is None or run.get("status") in _TERMINAL_RUN_STATUSES:
        return
    run["status"] = "queued"
    run["progress"] = max(0.0, min(float(run.get("progress") or 0.0), _RUN_PROGRESS_FLOORS["upload"]))
    run["updated_at"] = datetime.now(timezone.utc).isoformat()
    upload_stage = _get_run_stage(run, "upload")
    if upload_stage is not None and upload_stage.get("status") == "running":
        upload_stage["status"] = "completed"
        upload_stage["progress"] = max(float(upload_stage.get("progress") or 0.0), _RUN_PROGRESS_FLOORS["upload"])
        upload_stage["updated_at"] = run["updated_at"]
    _persist_run(run)
    _ensure_tool_queue_worker()


def _ensure_tool_queue_worker() -> None:
    global _RUN_QUEUE_WORKER
    _ensure_runs_loaded()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _RUN_QUEUE_WORKER is None or _RUN_QUEUE_WORKER.done():
        _RUN_QUEUE_WORKER = loop.create_task(_run_tool_queue_worker())


async def _run_tool_queue_worker() -> None:
    while True:
        run = _next_queued_run()
        if run is None:
            return
        run_id = str(run.get("run_id") or "")
        if not run_id:
            return
        current_task = asyncio.current_task()
        if current_task is not None:
            _RUN_TASKS[run_id] = current_task
        try:
            await _execute_persisted_run(run)
        except Exception as exc:
            _fail_run(run_id, str(exc))
        finally:
            _RUN_TASKS.pop(run_id, None)


def _next_queued_run() -> dict[str, Any] | None:
    queued = [run for run in _RUNS.values() if run.get("status") == "queued"]
    queued.sort(key=lambda item: str(item.get("created_at") or ""))
    return queued[0] if queued else None


async def _execute_persisted_run(run: dict[str, Any]) -> None:
    run_id = str(run.get("run_id") or "")
    tool = str(run.get("tool") or "").strip().lower()
    request = run.get("request") if isinstance(run.get("request"), dict) else {}
    if not run_id:
        raise RuntimeError("run_id is missing")
    if tool == "tts":
        reference_value = request.get("reference_path")
        await _execute_tts_run(
            run_id,
            text=str(request.get("text") or ""),
            original_text=str(request.get("original_text") or request.get("text") or ""),
            provider=str(request.get("provider") or "cosyvoice3"),
            mode=str(request.get("mode") or "zero_shot"),
            prompt_text=str(request.get("prompt_text") or ""),
            instruct_text=str(request.get("instruct_text") or ""),
            spk_id=str(request.get("spk_id") or ""),
            zero_shot_spk_id=str(request.get("zero_shot_spk_id") or ""),
            stream=bool(request.get("stream", True)),
            speed=float(request.get("speed") or 1.0),
            seed=int(request.get("seed") or 0),
            text_frontend=bool(request.get("text_frontend", True)),
            moss_duration_tokens=int(request.get("moss_duration_tokens") or 0),
            moss_max_new_tokens=int(request.get("moss_max_new_tokens") or 0),
            moss_temperature=float(request.get("moss_temperature") or 1.1),
            moss_top_p=float(request.get("moss_top_p") or 0.9),
            moss_top_k=int(request.get("moss_top_k") or 50),
            moss_repetition_penalty=float(request.get("moss_repetition_penalty") or 1.1),
            auto_prompt_text_asr=bool(request.get("auto_prompt_text_asr", True)),
            reference_path=Path(str(reference_value)) if reference_value else None,
        )
        return
    if tool == "asr":
        audio_path = Path(str(request.get("audio_path") or ""))
        if not audio_path.exists():
            raise RuntimeError(f"ASR uploaded audio is missing: {audio_path}")
        await _execute_asr_run(
            run_id,
            audio_path=audio_path,
            language=str(request.get("language") or "zh-CN"),
            prompt=str(request.get("prompt") or ""),
        )
        return
    if tool == "avatar":
        presenter_path = Path(str(request.get("presenter_path") or ""))
        audio_path = Path(str(request.get("audio_path") or ""))
        missing_paths = [str(path) for path in (presenter_path, audio_path) if not path.exists()]
        if missing_paths:
            raise RuntimeError(f"Avatar uploaded media is missing: {', '.join(missing_paths)}")
        await _execute_avatar_run(
            run_id,
            script=str(request.get("script") or ""),
            presenter_path=presenter_path,
            audio_path=audio_path,
        )
        return
    raise RuntimeError(f"Unsupported tool run type: {tool}")


def _create_run(tool: str, *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "run_id": run_id,
        "tool": tool,
        "status": "queued",
        "progress": 0.0,
        "request": _json_safe(request or {}),
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
    _persist_run(run)
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
    _persist_run(run)


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
    _persist_run(run)


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
    _persist_run(run)


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
    queued_runs = [item for item in _RUNS.values() if item.get("status") == "queued"]
    return {
        "run_id": run["run_id"],
        "tool": run["tool"],
        "status": run["status"],
        "progress": run["progress"],
        "queue_position": _queue_position(str(run["run_id"])),
        "queue_size": len(queued_runs),
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
    if run.get("status") == "queued":
        return "queued"
    for stage in run.get("stages", []):
        if stage.get("status") == "running":
            return str(stage.get("name") or "")
    if run.get("status") == "completed":
        return "completed"
    return str(run.get("status") or "queued")


def _current_stage_detail(run: dict[str, Any], current_stage: str) -> str:
    if current_stage == "queued":
        position = _queue_position(str(run.get("run_id") or ""))
        if position is not None:
            return f"等待后台队列执行，当前排第 {position} 个"
        return "等待后台队列执行"
    stage = _get_run_stage(run, current_stage)
    if stage is None:
        return ""
    return str(stage.get("detail") or "")


def _ensure_runs_loaded() -> None:
    global _RUNS_LOADED
    if _RUNS_LOADED:
        return
    _RUNS_LOADED = True
    if not _RUN_STORE_ROOT.exists():
        return
    for path in sorted(_RUN_STORE_ROOT.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or path.stem).strip()
        if not run_id:
            continue
        run["run_id"] = run_id
        _repair_run_shape(run)
        if run.get("status") not in _TERMINAL_RUN_STATUSES:
            _requeue_interrupted_run(run)
        _RUNS.setdefault(run_id, run)


def _repair_run_shape(run: dict[str, Any]) -> None:
    stages = run.get("stages")
    if not isinstance(stages, list):
        stages = []
    existing = {str(stage.get("name") or ""): stage for stage in stages if isinstance(stage, dict)}
    repaired = []
    for name in _RUN_STAGE_NAMES:
        stage = existing.get(name) or {}
        repaired.append({
            "name": name,
            "status": str(stage.get("status") or "pending"),
            "progress": _coerce_progress(stage.get("progress")) or 0.0,
            "detail": str(stage.get("detail") or ""),
            "updated_at": stage.get("updated_at"),
            **({"data": stage.get("data")} if isinstance(stage.get("data"), dict) else {}),
        })
    run["stages"] = repaired
    run.setdefault("status", "queued")
    run.setdefault("progress", 0.0)
    run.setdefault("request", {})
    run.setdefault("result", None)
    run.setdefault("error", None)
    run.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    run.setdefault("updated_at", run.get("created_at"))


def _requeue_interrupted_run(run: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for stage in run.get("stages", []):
        if stage.get("status") == "running":
            stage["status"] = "pending"
            stage["detail"] = "等待后台队列恢复执行"
            stage["updated_at"] = now
    run["status"] = "queued"
    run["error"] = None
    run["updated_at"] = now
    _persist_run(run)


def _persist_run(run: dict[str, Any]) -> None:
    try:
        _RUN_STORE_ROOT.mkdir(parents=True, exist_ok=True)
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            return
        path = _RUN_STORE_ROOT / f"{_safe_filename_part(run_id, fallback='run', max_length=64)}.json"
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(_json_safe(run), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        return


def _queue_position(run_id: str) -> int | None:
    run = _RUNS.get(run_id)
    if run is None or run.get("status") != "queued":
        return None
    queued = [item for item in _RUNS.values() if item.get("status") == "queued"]
    queued.sort(key=lambda item: str(item.get("created_at") or ""))
    for index, item in enumerate(queued, start=1):
        if item.get("run_id") == run_id:
            return index
    return None


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


def _build_tts_output_filename(
    *,
    created_at: datetime,
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
    segment_count: int,
) -> str:
    timestamp = created_at.astimezone().strftime("%Y%m%d_%H%M%S")
    parts = ["tts", timestamp, _safe_filename_part(mode, fallback="mode", max_length=28)]
    if spk_id:
        parts.append(f"spk-{_safe_filename_part(spk_id, fallback='speaker', max_length=36)}")
    if zero_shot_spk_id:
        parts.append(f"voice-{_safe_filename_part(zero_shot_spk_id, fallback='voice', max_length=36)}")
    if instruct_text:
        parts.append(f"inst-{_safe_filename_part(instruct_text, fallback='instruction', max_length=34)}")
    elif prompt_text:
        parts.append(f"prompt-{_safe_filename_part(prompt_text, fallback='prompt', max_length=34)}")
    if reference_path is not None:
        parts.append(f"ref-{_safe_filename_part(reference_path.stem, fallback='reference', max_length=34)}")
    parts.extend([
        f"speed{_format_filename_number(speed)}",
        f"seed{int(seed or 0)}",
        "stream" if stream else "batch",
        "frontend" if text_frontend else "rawtext",
    ])
    if segment_count > 1:
        parts.append(f"seg{segment_count}")
    filename = "_".join(part for part in parts if part)
    return _safe_upload_filename(f"{filename}.wav", fallback_suffix=".wav")


def _safe_filename_part(value: Any, *, fallback: str, max_length: int) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*#\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    cleaned = re.sub(r"\s+", "-", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in _WINDOWS_RESERVED_FILENAMES:
        cleaned = f"{cleaned}_file"
    return cleaned[:max(1, max_length)].strip(" ._") or fallback


def _format_filename_number(value: float) -> str:
    return f"{float(value or 0):.2f}".rstrip("0").rstrip(".").replace(".", "p")


def _tts_output_config_summary(
    *,
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
    segment_count: int,
) -> str:
    parts = [f"mode={mode}"]
    if spk_id:
        parts.append(f"spk_id={spk_id}")
    if zero_shot_spk_id:
        parts.append(f"zero_shot_spk_id={zero_shot_spk_id}")
    if reference_path is not None:
        parts.append(f"reference={reference_path.name}")
    if prompt_text:
        parts.append(f"prompt={_short_text(prompt_text, 32)}")
    if instruct_text:
        parts.append(f"instruct={_short_text(instruct_text, 32)}")
    parts.extend([
        f"speed={_format_config_number(speed)}",
        f"seed={int(seed or 0)}",
        f"stream={str(bool(stream)).lower()}",
        f"text_frontend={str(bool(text_frontend)).lower()}",
    ])
    if segment_count > 1:
        parts.append(f"segments={segment_count}")
    return " · ".join(parts)


def _moss_tts_output_config_summary(
    *,
    mode: str,
    prompt_text: str,
    reference_path: Path | None,
    duration_tokens: int,
    segment_duration_tokens: list[int],
    sampling_params: dict[str, Any],
    segment_count: int,
) -> str:
    parts = ["provider=moss_tts_local", f"mode={mode}"]
    if reference_path is not None:
        parts.append(f"reference={reference_path.name}")
    if prompt_text:
        parts.append(f"prompt={_short_text(prompt_text, 32)}")
    if duration_tokens > 0:
        parts.append(f"duration_tokens={duration_tokens}")
    elif segment_duration_tokens:
        if len(segment_duration_tokens) == 1:
            parts.append(f"auto_duration_tokens={segment_duration_tokens[0]}")
        else:
            parts.append(f"auto_duration_tokens={sum(segment_duration_tokens)}")
    for key in ("max_new_tokens", "temperature", "top_p", "top_k"):
        if key in sampling_params:
            parts.append(f"{key}={sampling_params[key]}")
    if segment_count > 1:
        parts.append(f"segments={segment_count}")
    return " · ".join(parts)


def _short_text(value: str, max_length: int) -> str:
    cleaned = _collapse_tts_text(value)
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max(1, max_length - 1)]}…"


def _format_config_number(value: float) -> str:
    return f"{float(value or 0):.3f}".rstrip("0").rstrip(".")


def _write_tts_output_metadata(output_path: Path, result: dict[str, Any]) -> None:
    metadata = {
        "created_at": result.get("created_at"),
        "display_name": result.get("display_name") or output_path.name,
        "config_summary": result.get("config_summary"),
        "config": {
            key: result.get(key)
            for key in (
                "provider",
                "mode",
                "prompt_text",
                "prompt_text_source",
                "instruct_text",
                "reference_audio",
                "spk_id",
                "zero_shot_spk_id",
                "stream",
                "speed",
                "seed",
                "text_frontend",
                "moss_duration_tokens",
                "moss_segment_duration_tokens",
                "sampling_params",
                "segment_count",
            )
        },
        "text": result.get("tts_text") or result.get("text") or "",
        "text_preview": _short_text(str(result.get("tts_text") or result.get("text") or ""), 120),
        "audio": {
            key: result.get(key)
            for key in ("format", "sample_rate", "duration", "source_format")
            if result.get(key) is not None
        },
    }
    output_path.with_suffix(f"{output_path.suffix}.json").write_text(
        json.dumps(_json_safe(metadata), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_tts_output_metadata(path: Path) -> dict[str, Any]:
    metadata_path = path.with_suffix(f"{path.suffix}.json")
    if not metadata_path.exists() or not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _translate_legacy_runtime_path(value: str) -> Path | None:
    requested = str(value or "").strip()
    if not requested:
        return None
    normalized = requested.replace("\\", "/")
    legacy_roots = (
        "F:/roughcut_outputs",
        "E:/WorkSpace/RoughCut/data/runtime",
    )
    for legacy_root in legacy_roots:
        if normalized.casefold() == legacy_root.casefold():
            return DEFAULT_OUTPUT_ROOT
        prefix = f"{legacy_root}/"
        if normalized.casefold().startswith(prefix.casefold()):
            suffix = normalized[len(prefix) :].strip("/")
            if suffix:
                return DEFAULT_OUTPUT_ROOT.joinpath(*suffix.split("/"))
            return DEFAULT_OUTPUT_ROOT
    return None


def _reference_audio_metadata_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.json")


def _is_reference_upload_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = _REFERENCE_UPLOAD_ROOT.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _read_reference_audio_metadata(path: Path) -> dict[str, Any]:
    if not _is_reference_upload_path(path):
        return {}
    metadata_path = _reference_audio_metadata_path(path)
    if not metadata_path.exists() or not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_reference_audio_prompt_text(path: Path) -> str:
    metadata = _read_reference_audio_metadata(path)
    prompt_text = metadata.get("prompt_text")
    return _collapse_tts_text(str(prompt_text or ""))


def _write_reference_audio_metadata(
    path: Path,
    *,
    prompt_text: str,
    prompt_text_source: str,
    provider: str,
    mode: str,
) -> None:
    if not _is_reference_upload_path(path):
        return
    cleaned_prompt_text = _collapse_tts_text(prompt_text)
    if not cleaned_prompt_text:
        return
    metadata_path = _reference_audio_metadata_path(path)
    existing = _read_reference_audio_metadata(path)
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        **existing,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "prompt_text": cleaned_prompt_text,
        "prompt_text_source": str(prompt_text_source or "manual"),
        "provider": str(provider or ""),
        "mode": str(mode or ""),
        "reference_audio": str(path),
    }
    try:
        metadata_path.write_text(json.dumps(_json_safe(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
        path.touch(exist_ok=True)
    except OSError:
        return


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
    items = _list_audio_artifact_history(
        root=_REFERENCE_UPLOAD_ROOT,
        source="参考上传",
        artifact_kind="reference-uploads",
        limit=limit,
        suffixes=_REFERENCE_AUDIO_SUFFIXES | _REFERENCE_VIDEO_SUFFIXES,
        dedupe=True,
    )
    for item in items:
        metadata = _read_reference_audio_metadata(Path(str(item.get("path") or "")))
        if not metadata:
            continue
        prompt_text = _collapse_tts_text(str(metadata.get("prompt_text") or ""))
        if prompt_text:
            item["prompt_text"] = prompt_text
            item["text_preview"] = _short_text(prompt_text, 120)
        item["prompt_text_source"] = metadata.get("prompt_text_source") or ""
        item["config"] = {
            key: metadata.get(key)
            for key in ("provider", "mode", "prompt_text_source")
            if metadata.get(key) is not None
        }
        item["created_at"] = metadata.get("created_at") or item.get("created_at")
        item["updated_at"] = metadata.get("updated_at") or item.get("updated_at")
    return items


def _list_tts_output_history(limit: int = _TTS_OUTPUT_HISTORY_LIMIT) -> list[dict[str, Any]]:
    items = _list_audio_artifact_history(
        root=_TTS_ROOT,
        source="生成音频",
        artifact_kind="tts",
        limit=limit,
        suffixes=_REFERENCE_AUDIO_SUFFIXES,
        dedupe=False,
    )
    for item in items:
        metadata = _read_tts_output_metadata(Path(str(item.get("path") or "")))
        if not metadata:
            continue
        item["created_at"] = metadata.get("created_at") or item.get("updated_at")
        item["display_name"] = metadata.get("display_name") or item.get("name")
        item["config_summary"] = metadata.get("config_summary") or ""
        item["text_preview"] = metadata.get("text_preview") or ""
        config = metadata.get("config")
        if isinstance(config, dict):
            item["config"] = _normalize_tts_output_config(config)
    return items


def _normalize_tts_output_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    reference_audio = normalized.get("reference_audio")
    if isinstance(reference_audio, str):
        translated = _translate_legacy_runtime_path(reference_audio)
        if translated is not None and translated.exists():
            normalized["reference_audio"] = str(translated)
    return normalized


def _resolve_reference_audio_history_path(value: str) -> Path:
    requested = str(value or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="reference_history_path is empty")
    raw_path = Path(requested)
    allowed_roots = (_REFERENCE_UPLOAD_ROOT.resolve(),)
    candidates = [raw_path]
    translated = _translate_legacy_runtime_path(requested)
    if translated is not None:
        candidates.append(translated)
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
    return _prepare_reference_audio(
        path,
        run_id=run_id,
        max_seconds=_MAX_REFERENCE_AUDIO_SEC,
        service_label="CosyVoice3",
    )


def _prepare_reference_audio_for_moss(path: Path, *, run_id: str) -> Path:
    return _prepare_reference_audio(
        path,
        run_id=run_id,
        max_seconds=_MOSS_REFERENCE_AUDIO_MAX_SEC,
        service_label="MOSS-TTS Local",
    )


def _prepare_reference_audio(path: Path, *, run_id: str, max_seconds: float, service_label: str) -> Path:
    suffix = path.suffix.lower()
    duration = _audio_duration_seconds(path)
    needs_conversion = suffix != ".wav"
    needs_trimming = duration is not None and duration > max_seconds
    if not needs_conversion and not needs_trimming:
        return path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if suffix in _REFERENCE_VIDEO_SUFFIXES:
            raise RuntimeError(f"参考视频需要 ffmpeg 自动提取音频并转换为 {service_label} 可用的 WAV")
        if needs_trimming and duration is not None:
            raise RuntimeError(f"参考音频 {duration:.1f}s 超过 {max_seconds:.0f}s；需要 ffmpeg 自动去除开头静音并截取")
        raise RuntimeError(f"参考音频需要 ffmpeg 转换为 {service_label} 可用的 WAV")
    _REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = _REFERENCE_ROOT / f"reference_{uuid.uuid4().hex[:12]}.wav"
    compress_long_silence = service_label == "MOSS-TTS Local"
    if suffix in _REFERENCE_VIDEO_SUFFIXES:
        detail = "正在从参考视频提取音频，转换为 16k 单声道 WAV"
    elif needs_trimming and duration is not None:
        detail = f"{service_label} 参考音频 {duration:.1f}s 超过 {max_seconds:.0f}s，正在提取有效语音并保留短停顿"
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
        _reference_audio_filter(compress_long_silence=compress_long_silence),
    ]
    if duration is None or needs_trimming:
        command.extend(["-t", str(float(max_seconds))])
    command.extend([
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ])
    result = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        fallback_command = [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-vn",
        ]
        if duration is None or needs_trimming:
            fallback_command.extend(["-t", str(float(max_seconds))])
        fallback_command.extend([
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ])
        fallback = subprocess.run(fallback_command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        if fallback.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
            output_path.unlink(missing_ok=True)
            detail = (fallback.stderr or result.stderr or "ffmpeg trim failed").strip().splitlines()[-1:]
            raise RuntimeError(f"Failed to prepare reference audio: {' '.join(detail)[:500]}")
    return output_path


def _reference_audio_filter(*, compress_long_silence: bool) -> str:
    if not compress_long_silence:
        return "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-45dB"
    return (
        "silenceremove="
        "start_periods=1:"
        "start_duration=0.2:"
        "start_threshold=-45dB:"
        "start_silence=0.08:"
        "stop_periods=-1:"
        f"stop_duration={_MOSS_REFERENCE_LONG_SILENCE_SEC}:"
        "stop_threshold=-45dB:"
        f"stop_silence={_MOSS_REFERENCE_KEEP_SILENCE_SEC}"
    )


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
            encoding="utf-8",
            errors="replace",
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


def _validate_tts_audio_output(path: Path, *, service_label: str, segment_index: int | None = None) -> float:
    duration = _probe_audio_duration(path)
    if duration >= _MIN_TTS_AUDIO_DURATION_SEC:
        return duration
    segment_label = f" segment {segment_index}" if segment_index is not None else ""
    size = path.stat().st_size if path.exists() else 0
    raise RuntimeError(
        f"{service_label} returned empty audio{segment_label} ({duration:.3f}s, {size} bytes). "
        "Check that reference_audio matches prompt_text and retry with a shorter target text or more stable sampling."
    )


def _validate_tts_audio_duration_for_text(
    duration: float,
    text: str,
    *,
    service_label: str,
    segment_index: int | None = None,
) -> None:
    cleaned = re.sub(r"\[S[1-5]\]|\$\{[^}]+\}", "", str(text or ""))
    text_chars = len(re.sub(r"\s+", "", cleaned))
    if text_chars < _MIN_DURATION_TEXT_CHARS:
        return
    min_duration = min(_MAX_DURATION_VALIDATION_MIN_SEC, text_chars * _MIN_DURATION_PER_TEXT_CHAR_SEC)
    if float(duration or 0.0) < min_duration:
        segment_label = f" segment {segment_index}" if segment_index is not None else ""
        raise RuntimeError(
            f"{service_label} returned audio{segment_label} that is too short for the target text "
            f"({duration:.1f}s for {text_chars} chars; expected at least {min_duration:.1f}s). "
            "Check that reference_audio matches prompt_text and retry with a shorter target text or more stable sampling."
        )


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
