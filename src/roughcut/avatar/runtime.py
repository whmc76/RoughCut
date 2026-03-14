from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.media.probe import probe

_DEFAULT_HEYGEM_ROOT = Path("E:/WorkSpace/heygem/data")
_DEFAULT_VOICE_ROOT = Path("data/voice_refs")
_CONTAINER_DATA_ROOT = Path("/code/data")
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 600.0
_HEYGEM_HEALTH_TIMEOUT_SECONDS = 2.5
_MIN_PREVIEW_AUDIO_SECONDS = 1.5
_MAX_PREVIEW_AUDIO_SECONDS = 18.0
_HEYGEM_PREVIEW_SERVICE_CACHE: dict[str, bool | None] = {}


def heygem_shared_root() -> Path:
    root_env = os.getenv("HEYGEM_SHARED_ROOT")
    if root_env:
        root = Path(root_env)
    else:
        root = _DEFAULT_HEYGEM_ROOT
    (root / "inputs" / "audio").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "video").mkdir(parents=True, exist_ok=True)
    (root / "temp").mkdir(parents=True, exist_ok=True)
    (root / "result").mkdir(parents=True, exist_ok=True)
    return root


def heygem_voice_root() -> Path:
    root_env = os.getenv("HEYGEM_VOICE_ROOT")
    if root_env:
        root = Path(root_env)
    else:
        root = _DEFAULT_VOICE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def heygem_container_input_path(kind: str, name: str) -> str:
    return str((_CONTAINER_DATA_ROOT / "inputs" / kind / name).as_posix())


async def is_heygem_training_available() -> bool:
    settings = get_settings()
    base_url = str(settings.avatar_training_api_base_url or "").strip().rstrip("/")
    if not base_url:
        return False

    timeout = httpx.Timeout(10.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for method, path in (("GET", "/health"), ("GET", "/healthz"), ("POST", "/v1/health")):
            try:
                response = await client.request(method, f"{base_url}{path}")
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue
            if str(payload.get("status") or "").lower() == "ok":
                return True
    return False


async def is_heygem_preview_available() -> bool:
    settings = get_settings()
    candidates = _avatar_preview_bases(settings.avatar_api_base_url, settings.avatar_training_api_base_url)
    if not candidates:
        return False
    for candidate in candidates:
        status = await _is_heygem_training_only_service(candidate)
        if status is False:
            return True
    return False


async def convert_voice_sample_to_wav(source_path: Path, output_path: Path) -> Path:
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg wav conversion failed: {result.stderr[-1000:]}")
    return output_path


async def prepare_voice_sample_artifacts(
    file_record: dict[str, Any],
    *,
    attempt_preprocess: bool = True,
    require_preprocess: bool = False,
) -> dict[str, Any]:
    source_path = Path(str(file_record.get("path") or ""))
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    artifacts = dict(file_record.get("artifacts") or {})
    file_id = "".join(ch for ch in str(file_record.get("id") or "") if ch.isalnum())[:8] or uuid.uuid4().hex[:8]
    normalized_dir = source_path.parent / "derived"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = normalized_dir / f"voice_{file_id}_16k_mono.wav"
    await convert_voice_sample_to_wav(source_path, normalized_path)

    staged_name = f"voice_{file_id}.wav"
    staged_path = heygem_voice_root() / staged_name
    shutil.copy2(normalized_path, staged_path)

    artifacts["normalized_wav_path"] = str(normalized_path)
    artifacts["training_reference_name"] = staged_name
    if attempt_preprocess:
        try:
            preprocess_result = await preprocess_voice_sample(staged_name, normalized_path=normalized_path)
        except Exception as exc:
            artifacts["training_preprocess_error"] = str(exc)
            artifacts.pop("training_preprocess", None)
            file_record["artifacts"] = artifacts
            if require_preprocess:
                raise RuntimeError(str(exc)) from exc
            return file_record
        artifacts["training_preprocess"] = preprocess_result
        artifacts.pop("training_preprocess_error", None)
    file_record["artifacts"] = artifacts
    return file_record


async def preprocess_voice_sample(
    reference_name: str,
    *,
    lang: str = "zh",
    normalized_path: Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    base_url = str(settings.avatar_training_api_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("avatar_training_api_base_url is not configured")
    if not await is_heygem_training_available():
        raise RuntimeError(f"voice synthesis service unavailable: {base_url}")
    return {
        "provider": "indextts2",
        "reference_audio": reference_name,
        "reference_audio_text": "",
        "lang": lang,
        "mode": "direct_reference_upload",
        "normalized_wav_path": str(normalized_path) if normalized_path else "",
    }


async def synthesize_preview_audio(
    *,
    script: str,
    preprocess_result: dict[str, Any],
    output_path: Path,
    training_reference_name: str = "",
    lang: str = "zh",
) -> Path:
    settings = get_settings()
    base_url = str(settings.avatar_training_api_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("avatar_training_api_base_url is not configured")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    reference_audio_path = _resolve_indextts_reference_path(
        preprocess_result=preprocess_result,
        training_reference_name=training_reference_name,
    )
    if reference_audio_path is None or not reference_audio_path.exists():
        raise RuntimeError("indextts2 reference audio is missing")

    emotion_text, emotion_strength = _infer_indextts2_preview_emotion(script)
    payload = {
        "input": script,
        "voice": "default",
        "model": "indextts2",
        "response_format": "wav",
        "provider_options": {
            "output_mode": "base64",
            "speaker_audio_base64": base64.b64encode(reference_audio_path.read_bytes()).decode("utf-8"),
            "emo_text": emotion_text,
            "use_emo_text": True,
            "auto_mix_emotion": True,
            "emotion_strength": emotion_strength,
            "interval_silence": 120,
            "max_text_tokens_per_segment": 120,
        },
    }

    timeout = httpx.Timeout(300.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{base_url}/v1/audio/speech", json=payload)
        response.raise_for_status()
        body = response.json()
        audio_b64 = str(body.get("audio_base64") or "").strip()
        if not audio_b64:
            raise RuntimeError("indextts2 did not return audio_base64")
        output_path.write_bytes(base64.b64decode(audio_b64))
    return output_path


async def generate_avatar_preview(
    *,
    profile: dict[str, Any],
    script: str,
) -> dict[str, Any]:
    voice_file = _pick_file(profile, "voice_sample")
    video_file = _pick_file(profile, "speaking_video")
    if voice_file is None:
        raise RuntimeError("missing_voice_sample")
    if video_file is None:
        raise RuntimeError("missing_speaking_video")

    voice_file = await _ensure_voice_prepared(voice_file, attempt_training_preprocess=False)
    voice_artifacts = dict(voice_file.get("artifacts") or {})
    normalized_audio_path = Path(str(voice_artifacts.get("normalized_wav_path") or ""))
    if not normalized_audio_path.exists():
        raise RuntimeError("missing_normalized_voice_sample")

    preview_id = uuid.uuid4().hex
    source_video_path = Path(str(video_file.get("path") or ""))
    if not source_video_path.exists():
        raise RuntimeError(f"preview source video missing: {source_video_path}")

    staged_video_url = _stage_video_for_heygem(source_video_path, preview_id=preview_id)
    shared_root = heygem_shared_root()
    staged_audio_path = shared_root / "inputs" / "audio" / f"{preview_id}.source.wav"
    await _prepare_direct_preview_audio(
        source_audio_path=normalized_audio_path,
        output_path=staged_audio_path,
        script=script,
        source_video_path=source_video_path,
    )
    task_code, result_payload = await _run_heygem_preview_with_retry(
        audio_name=staged_audio_path.name,
        video_url=staged_video_url,
        preview_id=preview_id,
    )
    local_result_path = _resolve_local_result_path(str(result_payload.get("result") or ""))
    local_result_path = _require_generated_preview_output(
        local_result_path=local_result_path,
        source_video_path=source_video_path,
        source_audio_path=staged_audio_path,
    )
    return _build_preview_run(
        profile=profile,
        voice_file=voice_file,
        video_file=video_file,
        preview_id=preview_id,
        script=script,
        task_code=task_code,
        result_payload=result_payload,
        local_result_path=local_result_path,
        preview_mode="source_audio_direct",
        fallback_reason=None,
    )


def _pick_file(profile: dict[str, Any], role: str) -> dict[str, Any] | None:
    for file_record in profile.get("files") or []:
        if str(file_record.get("role") or "") == role:
            return file_record
    return None


def _estimate_min_preview_audio_seconds(script: str) -> float:
    normalized = "".join(ch for ch in str(script or "") if ch.isalnum() or ch.isspace()).strip()
    chars = max(1, len(normalized))
    return max(_MIN_PREVIEW_AUDIO_SECONDS, min(chars * 0.18, _MAX_PREVIEW_AUDIO_SECONDS))


async def _prepare_direct_preview_audio(
    *,
    source_audio_path: Path,
    output_path: Path,
    script: str,
    source_video_path: Path,
) -> Path:
    if not source_audio_path.exists():
        raise RuntimeError(f"preview audio missing: {source_audio_path}")
    if not source_video_path.exists():
        raise RuntimeError(f"preview source video missing: {source_video_path}")

    audio_meta = await probe(source_audio_path)
    audio_duration = float(audio_meta.duration or 0.0)
    if audio_duration <= 0:
        raise RuntimeError(f"preview audio invalid: duration is zero for {source_audio_path.name}")

    video_meta = await probe(source_video_path)
    video_duration = float(video_meta.duration or 0.0)
    if video_duration <= 0:
        raise RuntimeError(f"preview source video invalid: duration is zero for {source_video_path.name}")

    # HeyGem preview is unstable when fed a long reference track, especially when it
    # exceeds the presenter clip length. Keep preview audio short and bounded by video.
    target_duration = min(audio_duration, video_duration, _MAX_PREVIEW_AUDIO_SECONDS)
    min_duration = min(_estimate_min_preview_audio_seconds(script), video_duration, _MAX_PREVIEW_AUDIO_SECONDS)
    target_duration = max(min_duration, target_duration)
    if target_duration <= 0:
        raise RuntimeError("preview audio target duration is invalid")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_audio_path),
        "-af",
        f"apad=pad_dur={max(0.0, target_duration - audio_duration):.3f}",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-t",
        f"{target_duration:.3f}",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ),
    )
    if result.returncode != 0:
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"preview audio trim failed: {result.stderr[-1000:]}")
    return output_path


async def _ensure_audio_duration(audio_path: Path, script: str) -> None:
    if not audio_path.exists():
        raise RuntimeError(f"preview audio missing: {audio_path}")

    meta = await probe(audio_path)
    duration = float(meta.duration or 0.0)
    if duration <= 0:
        raise RuntimeError(f"preview audio invalid: duration is zero for {audio_path.name}")

    min_duration = _estimate_min_preview_audio_seconds(script)
    if duration >= min_duration:
        return

    pad_seconds = max(0.0, min_duration - duration)
    temp_output = audio_path.with_suffix(".preview_pad.wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-af",
        f"apad=pad_dur={pad_seconds:.3f}",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-t",
        f"{min_duration:.3f}",
        str(temp_output),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ),
    )
    if result.returncode != 0:
        if temp_output.exists():
            temp_output.unlink()
        raise RuntimeError(f"preview audio pad failed: {result.stderr[-1000:]}")
    temp_output.replace(audio_path)


async def _ensure_voice_prepared(
    file_record: dict[str, Any],
    *,
    attempt_training_preprocess: bool = True,
) -> dict[str, Any]:
    artifacts = dict(file_record.get("artifacts") or {})
    normalized_path = Path(str(artifacts.get("normalized_wav_path") or ""))
    if normalized_path.exists() and artifacts.get("training_preprocess"):
        return file_record
    if normalized_path.exists() and not attempt_training_preprocess:
        return file_record
    return await prepare_voice_sample_artifacts(
        file_record,
        attempt_preprocess=attempt_training_preprocess and await is_heygem_training_available(),
        require_preprocess=False,
    )


def _looks_like_stale_training_preprocess(preprocess_result: dict[str, Any], *, response_text: str) -> bool:
    reference_audio = str(preprocess_result.get("asr_format_audio_url") or "").strip()
    if "/code/sessions/" in reference_audio:
        return True
    lowered = str(response_text or "").lower()
    return "no such file or directory" in lowered or "filenotfounderror" in lowered


def _resolve_training_reference_audio(
    *,
    preprocess_result: dict[str, Any],
    training_reference_name: str,
) -> str:
    session_audio = str(preprocess_result.get("asr_format_audio_url") or "").strip()
    if session_audio and "/code/data/" in session_audio:
        return session_audio

    reference_name = Path(training_reference_name).name.strip()
    if reference_name:
        for candidate in (
            f"/code/data/format_denoise_{reference_name}",
            f"/code/data/denoise_{reference_name}",
            f"/code/data/{reference_name}",
        ):
            if _heygem_voice_reference_exists(candidate):
                return candidate

    first_segment = session_audio.split("|||", 1)[0].strip()
    return first_segment or session_audio


def _resolve_indextts_reference_path(
    *,
    preprocess_result: dict[str, Any],
    training_reference_name: str,
) -> Path | None:
    normalized = Path(str(preprocess_result.get("normalized_wav_path") or "")).expanduser()
    if normalized.exists():
        return normalized

    reference_name = Path(training_reference_name).name.strip()
    if reference_name:
        candidate = heygem_voice_root() / reference_name
        if candidate.exists():
            return candidate
    return None


def _infer_indextts2_preview_emotion(script: str) -> tuple[str, float]:
    text = str(script or "").strip()
    if any(token in text for token in ("欢迎", "大家好", "今天", "快速看看")):
        return "自然亲切，带一点开场吸引力。", 0.32
    if any(token in text for token in ("终于", "惊喜", "太强", "震撼")):
        return "轻微兴奋但保持自然，重点词更有精神。", 0.36
    return "自然口语化，语气稳定，轻微强调重点。", 0.28


def _resolve_training_reference_text(preprocess_result: dict[str, Any]) -> str:
    raw_text = str(preprocess_result.get("reference_audio_text") or "").strip()
    if not raw_text:
        return ""
    parts = [part.strip() for part in raw_text.split("|||") if part.strip()]
    return " ".join(parts) if parts else raw_text


def _heygem_voice_reference_exists(container_path: str) -> bool:
    prefix = "/code/data/"
    if not container_path.startswith(prefix):
        return False
    relative_name = container_path[len(prefix) :].strip()
    if not relative_name:
        return False
    return (heygem_voice_root() / relative_name).exists()


def _stage_video_for_heygem(source_path: Path, *, preview_id: str) -> str:
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    target_name = f"{preview_id}_{source_path.name}"
    target_path = heygem_shared_root() / "inputs" / "video" / target_name
    shutil.copy2(source_path, target_path)
    return heygem_container_input_path("video", target_name)


async def _submit_heygem_preview(
    *,
    audio_name: str,
    video_url: str,
    task_code: str,
) -> dict[str, Any]:
    settings = get_settings()
    configured_candidates = _avatar_preview_bases(settings.avatar_api_base_url, settings.avatar_training_api_base_url)
    candidates = []
    preview_skipped_candidates = []
    unreachable_candidates = []
    for candidate in configured_candidates:
        service_status = await _is_heygem_training_only_service(candidate)
        if service_status is None:
            unreachable_candidates.append(candidate)
            continue
        if service_status:
            preview_skipped_candidates.append(candidate)
            continue
        candidates.append(candidate)

    if not candidates:
        if preview_skipped_candidates and not unreachable_candidates:
            raise RuntimeError(
                "No preview-capable HeyGem endpoint found; the following configured services are training-only: "
                + ", ".join(preview_skipped_candidates)
            )
        if preview_skipped_candidates and unreachable_candidates:
            raise RuntimeError(
                "No preview-capable HeyGem endpoint found; training-only endpoints: "
                + ", ".join(preview_skipped_candidates)
                + "; unreachable endpoints: "
                + ", ".join(unreachable_candidates)
            )
        if unreachable_candidates:
            raise RuntimeError(
                "No preview-capable HeyGem endpoint found; the following configured endpoints are unreachable: "
                + ", ".join(unreachable_candidates)
            )
        raise RuntimeError("avatar_api_base_url is not configured")

    last_error: Exception | None = None
    for base_url in candidates:
        try:
            return await _submit_heygem_preview_to_base(
                audio_name=audio_name,
                video_url=video_url,
                task_code=task_code,
                base_url=base_url,
            )
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RuntimeError("heygem preview service unavailable")


async def _submit_heygem_preview_to_base(
    *,
    audio_name: str,
    video_url: str,
    task_code: str,
    base_url: str,
) -> dict[str, Any]:
    service_status = await _is_heygem_training_only_service(base_url)
    if service_status is None:
        raise RuntimeError(f"endpoint {base_url} is unreachable for avatar preview")
    if service_status:
        raise RuntimeError(f"endpoint {base_url} is training-only and does not expose avatar preview APIs")

    submit_payload = {
        "audio_url": heygem_container_input_path("audio", audio_name),
        "video_url": video_url,
        "code": task_code,
        "watermark_switch": 0,
        "digital_auth": 0,
        "chaofen": 0,
        "pn": 1,
    }
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_error: Exception | None = None
        endpoint_candidates = _build_heygem_submit_endpoints(base_url)
        for endpoints in endpoint_candidates:
            task_started = False
            try:
                response = await client.post(endpoints["submit"], json=submit_payload)
                response.raise_for_status()
                submit_result = response.json()
                if int(submit_result.get("code") or -1) != 10000:
                    raise RuntimeError(
                        str(submit_result.get("msg") or f"heygem submit failed from {endpoints['submit']}")
                    )

                task_started = True
                started_at = time.monotonic()
                while time.monotonic() - started_at < _POLL_TIMEOUT_SECONDS:
                    query_response = await client.get(endpoints["query"], params={"code": task_code})
                    query_response.raise_for_status()
                    payload = query_response.json()
                    payload_code = int(payload.get("code") or 0)
                    if payload_code == 10004:
                        completed_result = _resolve_completed_task_result(task_code)
                        if completed_result is not None:
                            return {
                                "status": 2,
                                "result": f"/{completed_result.name}",
                            }
                    data = payload.get("data") or {}
                    status_value = int(data.get("status") or 0)
                    if status_value == 2:
                        return data
                    if status_value == 3:
                        raise RuntimeError(str(data.get("msg") or f"heygem preview failed from {endpoints['query']}"))
                    await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            except Exception as exc:
                if task_started:
                    raise RuntimeError(
                        f"heygem preview task failed from {endpoints['submit']}->{endpoints['query']}: {exc}"
                    ) from exc
                last_error = exc
                continue
        if last_error is None:
            raise RuntimeError("heygem preview failed")
        available_endpoints = [f"{item['submit']}->{item['query']}" for item in endpoint_candidates]
        raise RuntimeError(
            f"heygem preview failed on {base_url}; tried={', '.join(available_endpoints)}; last_error={last_error}"
        ) from last_error


def _avatar_preview_bases(*bases: str | None) -> list[str]:
    candidates: list[str] = []
    for raw in bases:
        base = str(raw or "").strip().rstrip("/")
        if base and base not in candidates:
            candidates.append(base)
    return candidates


async def _is_heygem_training_only_service(base_url: str) -> bool | None:
    normalized_base = str(base_url or "").strip().rstrip("/")
    if not normalized_base:
        return True
    if normalized_base in _HEYGEM_PREVIEW_SERVICE_CACHE:
        return _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base]

    timeout = httpx.Timeout(_HEYGEM_HEALTH_TIMEOUT_SECONDS, connect=1.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{normalized_base}/json")
            response.raise_for_status()
            openapi_spec = response.json()
    except Exception:
        preview_probe = await _probe_heygem_preview_endpoints(normalized_base)
        if preview_probe is not None:
            _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = preview_probe
            return preview_probe
        training_probe = await _probe_heygem_training_endpoint(normalized_base)
        if training_probe is not None:
            _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = training_probe
            return training_probe
        return None

    paths = openapi_spec.get("paths")
    if not isinstance(paths, dict):
        _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = False
        return False

    has_training_endpoints = "/v1/preprocess_and_tran" in paths and "/v1/invoke" in paths
    has_preview_endpoints = any(
        key in paths
        for key in (
            "/easy/submit",
            "/easy/query",
            "/v1/easy/submit",
            "/v1/easy/query",
            "/api/easy/submit",
            "/api/easy/query",
            "/v1/submit",
            "/v1/query",
            "/submit",
            "/query",
        )
    )
    is_training_only = has_training_endpoints and not has_preview_endpoints
    _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = is_training_only
    return is_training_only


async def _probe_heygem_preview_endpoints(base_url: str) -> bool | None:
    timeout = httpx.Timeout(_HEYGEM_HEALTH_TIMEOUT_SECONDS, connect=1.0)
    for path in ("/easy/query?code=healthcheck", "/v1/easy/query?code=healthcheck", "/query?code=healthcheck"):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{base_url}{path}")
            if response.status_code < 500:
                return False
        except Exception:
            continue
    return None


async def _probe_heygem_training_endpoint(base_url: str) -> bool | None:
    timeout = httpx.Timeout(_HEYGEM_HEALTH_TIMEOUT_SECONDS, connect=1.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base_url}/v1/health")
        if response.status_code < 500:
            return True
    except Exception:
        return None
    return None


def _build_heygem_submit_endpoints(base_url: str) -> list[dict[str, str]]:
    base = base_url.rstrip("/")
    candidates = [
        ("/easy/submit", "/easy/query"),
        ("/v1/easy/submit", "/v1/easy/query"),
        ("/api/easy/submit", "/api/easy/query"),
        ("/v1/submit", "/v1/query"),
        ("/submit", "/query"),
    ]
    endpoints: list[dict[str, str]] = []
    for submit_suffix, query_suffix in candidates:
        submit_url = f"{base}{submit_suffix}"
        if not any(item["submit"] == submit_url for item in endpoints):
            endpoints.append({
                "submit": submit_url,
                "query": f"{base}{query_suffix}",
            })
    return endpoints


def _avatar_service_bases(*bases: str | None) -> list[str]:
    candidates: list[str] = []
    for raw in bases:
        base = str(raw or "").strip().rstrip("/")
        if base and base not in candidates:
            candidates.append(base)
    return candidates


async def _run_heygem_preview_with_retry(
    *,
    audio_name: str,
    video_url: str,
    preview_id: str,
) -> tuple[str, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(3):
        task_code = f"avatar-preview-{preview_id[:6]}-{attempt}"
        try:
            result_payload = await _submit_heygem_preview(
                audio_name=audio_name,
                video_url=video_url,
                task_code=task_code,
            )
            return task_code, result_payload
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if (
                attempt >= 2
                or (
                    "float division by zero" not in message
                    and "busy" not in message
                    and "all connection attempts failed" not in message
                )
            ):
                raise
            await asyncio.sleep(2.0 + attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("heygem preview failed")


def _build_preview_run(
    *,
    profile: dict[str, Any],
    voice_file: dict[str, Any],
    video_file: dict[str, Any],
    preview_id: str,
    script: str,
    task_code: str,
    result_payload: dict[str, Any],
    local_result_path: Path | None,
    preview_mode: str,
    fallback_reason: str | None,
) -> dict[str, Any]:
    if local_result_path is None or not local_result_path.exists():
        raise RuntimeError("preview_result_missing")

    profile_dir_value = str(profile.get("profile_dir") or "").strip()
    if profile_dir_value:
        profile_dir = Path(profile_dir_value)
    else:
        profile_dir = Path(str(video_file.get("path") or "")).resolve().parent
    preview_dir = profile_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    stored_path = preview_dir / f"{preview_id}.mp4"
    shutil.copy2(local_result_path, stored_path)

    width, height, duration_seconds = _probe_video_info(stored_path)
    return {
        "id": preview_id,
        "status": "completed",
        "script": script,
        "task_code": task_code,
        "source_voice_file_id": str(voice_file.get("id") or ""),
        "source_video_file_id": str(video_file.get("id") or ""),
        "output_path": str(stored_path),
        "output_size_bytes": stored_path.stat().st_size,
        "duration_sec": duration_seconds if duration_seconds is not None else _millis_to_seconds(result_payload.get("video_duration")),
        "width": width if width is not None else result_payload.get("width"),
        "height": height if height is not None else result_payload.get("height"),
        "preview_mode": preview_mode,
        "fallback_reason": fallback_reason,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _probe_video_info(video_path: Path) -> tuple[int | None, int | None, float | None]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        return None, None, None

    try:
        payload = json.loads(result.stdout or "{}")
        format_payload = payload.get("format") or {}
        duration = float(format_payload.get("duration") or 0.0)

        width = None
        height = None
        streams = payload.get("streams") or []
        for stream in streams:
            if str(stream.get("codec_type") or "").lower() == "video":
                width = int(stream.get("width") or 0) or None
                height = int(stream.get("height") or 0) or None
                break

        if width is not None and height is not None and duration > 0:
            return width, height, round(duration, 3)
    except Exception:
        return None, None, None

    return None, None, None


def _require_generated_preview_output(
    *,
    local_result_path: Path | None,
    source_video_path: Path,
    source_audio_path: Path | None,
) -> Path:
    if local_result_path is None or not local_result_path.exists():
        raise RuntimeError("heygem_preview_result_missing")
    if _is_result_source_path(local_result_path, source_video_path=source_video_path):
        raise RuntimeError("heygem_preview_result_points_to_source_video")
    if not _is_valid_generated_preview(local_result_path):
        raise RuntimeError("heygem_preview_result_invalid")
    return _ensure_preview_has_audio(
        preview_path=local_result_path,
        source_audio_path=source_audio_path,
    )


def _ensure_preview_has_audio(*, preview_path: Path, source_audio_path: Path | None) -> Path:
    if source_audio_path is None or not source_audio_path.exists():
        return preview_path

    if _has_audio_stream(preview_path):
        return preview_path

    repaired_path = preview_path.with_name(f"{preview_path.stem}.audio{preview_path.suffix}")
    _merge_preview_audio(
        source_video_path=preview_path,
        source_audio_path=source_audio_path,
        output_path=repaired_path,
    )
    if repaired_path.exists() and repaired_path.stat().st_size > 0:
        repaired_path.replace(preview_path)
        return preview_path

    raise RuntimeError("preview audio merge failed")


def _has_audio_stream(candidate: Path) -> bool:
    if not candidate.exists():
        return False

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        str(candidate),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        return False

    try:
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        return any(str((stream.get("codec_type") or "")).lower() == "audio" for stream in streams)
    except Exception:
        return False


def _merge_preview_audio(
    *,
    source_video_path: Path,
    source_audio_path: Path,
    output_path: Path,
) -> None:
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_video_path),
        "-i",
        str(source_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return

    fallback_command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_video_path),
        "-i",
        str(source_audio_path),
        "-filter_complex",
        "[0:v]null[v]",
        "-map",
        "[v]",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
        "-b:a",
        "160k",
        "-shortest",
        str(output_path),
    ]
    fallback_result = subprocess.run(
        fallback_command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if fallback_result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"preview audio merge failed: {result.stderr[-1000:] or fallback_result.stderr[-1000:]}")


def _is_valid_generated_preview(candidate: Path) -> bool:
    if candidate.stat().st_size < 1024:
        return False

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        str(candidate),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        return False

    try:
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        for stream in streams:
            if str(stream.get("codec_type") or "").lower() == "video":
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
                duration = float(stream.get("duration") or 0.0)
                if width > 0 and height > 0 and duration >= 0.1:
                    return True
    except Exception:
        return False
    return False


def _is_result_source_path(result_path: Path, *, source_video_path: Path) -> bool:
    try:
        if result_path.exists() and source_video_path.exists() and result_path.resolve() == source_video_path.resolve():
            return True
        if result_path.exists() and source_video_path.exists() and _is_exact_file_duplicate(result_path, source_video_path):
            return True
    except Exception:
        return True

    try:
        inputs_root = (heygem_shared_root() / "inputs").resolve()
        if result_path.resolve().is_relative_to(inputs_root):
            return True
    except Exception:
        pass
    return False


def _render_local_preview_fallback(
    *,
    preview_id: str,
    source_video_path: Path,
    source_audio_path: Path | None,
    output_path: Path,
) -> None:
    if not source_video_path.exists():
        raise RuntimeError(f"preview source video missing: {source_video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink(missing_ok=True)

    if source_audio_path is not None and source_audio_path.exists():
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_video_path),
            "-i",
            str(source_audio_path),
            "-filter_complex",
            (
                "[0:v]drawbox=x=0:y=0:w=iw:h=ih*0.1:color=black@0.26:t=fill,"
                "eq=contrast=1.18:brightness=-0.03,"
                "hue=h=0.02:s=1.12[vout]"
            ),
            "-map",
            "[vout]",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-shortest",
            str(output_path),
        ]
    else:
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_video_path),
            "-filter_complex",
            (
                "[0:v]drawbox=x=0:y=0:w=iw:h=ih*0.1:color=black@0.26:t=fill,"
                "eq=contrast=1.18:brightness=-0.03,"
                "hue=h=0.02:s=1.12[vout]"
            ),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            str(output_path),
        ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"preview fallback render failed: {result.stderr[-1000:]}")


def _resolve_local_result_path(result_value: str) -> Path | None:
    if not result_value:
        return None
    shared_root = heygem_shared_root()
    candidates = [
        shared_root / "temp" / result_value.lstrip("/"),
        shared_root / "result" / result_value.lstrip("/"),
        shared_root / result_value.lstrip("/"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_completed_task_result(task_code: str) -> Path | None:
    if not task_code:
        return None
    return _resolve_local_result_path(f"/{task_code}-r.mp4")


def _is_exact_file_duplicate(left: Path, right: Path) -> bool:
    if not (left.exists() and right.exists()):
        return False

    left_stat = left.stat()
    right_stat = right.stat()
    if left_stat.st_size != right_stat.st_size:
        return False

    def _md5(path: Path) -> str:
        hasher = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    return _md5(left) == _md5(right)


def _millis_to_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value) / 1000.0, 3)
    except Exception:
        return None
