from __future__ import annotations

import shutil
import subprocess
import time
import uuid
import os
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import DEFAULT_HEYGEM_SHARED_ROOT, get_settings, resolve_heygem_shared_root
from roughcut.docker_gpu_guard import hold_managed_gpu_services
from roughcut.providers.avatar.base import AvatarProvider

_DEFAULT_SHARED_ROOTS = (
    DEFAULT_HEYGEM_SHARED_ROOT,
    Path("D:/duix_avatar_data/face2face"),
    Path("d:/duix_avatar_data/face2face"),
)
_CONTAINER_VIDEO_ROOT = Path("/code/data/inputs/video")
_POLL_INTERVAL_SECONDS = 2.0
_TASK_TIMEOUT_MIN_SECONDS = 600.0
_TASK_TIMEOUT_MAX_SECONDS = 3600.0
_TASK_TIMEOUT_AUDIO_RATIO = 3.0
_TASK_TIMEOUT_BUFFER_SECONDS = 180.0
_HEYGEM_TRAINING_PROBE_TIMEOUT_SECONDS = 2.0
_HEYGEM_PREVIEW_SERVICE_CACHE: dict[str, bool] = {}
_SHARED_AUDIO_READY_RETRIES = 12
_SHARED_AUDIO_READY_RETRY_SECONDS = 1.0
_SHARED_AUDIO_SETTLE_FLOOR_SECONDS = 0.5
_SHARED_AUDIO_SETTLE_MAX_SECONDS = 8.0
_SHARED_AUDIO_SETTLE_BYTES_PER_SECOND = 8 * 1024 * 1024
_SEGMENT_BUSY_RETRY_DELAYS_SECONDS = (2.0, 4.0, 6.0, 8.0, 10.0)
_SEGMENT_BUSY_MAX_WAIT_SECONDS = 90.0
_RESULT_READY_RETRIES = 30
_RESULT_READY_RETRY_SECONDS = 2.0


class HeyGemAvatarProvider(AvatarProvider):
    def build_render_request(
        self,
        *,
        job_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        settings = get_settings()
        base_url = settings.avatar_api_base_url.rstrip("/")
        return {
            "provider": "heygem",
            "base_url": base_url,
            "submit_endpoint": base_url + "/easy/submit",
            "query_endpoint": base_url + "/easy/query",
            "job_id": job_id,
            "presenter_id": plan.get("presenter_id") or settings.avatar_presenter_id,
            "layout_template": plan.get("layout_template") or settings.avatar_layout_template,
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "script": segment.get("script"),
                    "start_time": segment.get("start_time"),
                    "duration_sec": segment.get("duration_sec"),
                    "audio_url": segment.get("audio_url"),
                }
                for segment in (plan.get("segments") or [])
            ],
        }

    def execute_render(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        presenter_id = str(request.get("presenter_id") or "").strip()
        if not presenter_id:
            return {
                "provider": "heygem",
                "job_id": job_id,
                "status": "skipped",
                "reason": "missing_presenter_id",
                "segments": [],
            }

        presenter_source = _resolve_presenter_source(presenter_id, job_id=job_id)
        if not presenter_source:
            return {
                "provider": "heygem",
                "job_id": job_id,
                "status": "failed",
                "reason": "presenter_source_not_found",
                "presenter_id": presenter_id,
                "segments": [],
            }

        headers: dict[str, str] = {}
        settings = get_settings()
        if str(settings.avatar_api_key or "").strip():
            headers["Authorization"] = f"Bearer {settings.avatar_api_key.strip()}"

        segments = list(request.get("segments") or [])
        if not segments:
            return {
                "provider": "heygem",
                "job_id": job_id,
                "status": "skipped",
                "reason": "empty_segments",
                "segments": [],
            }

        timeout = httpx.Timeout(30.0, connect=10.0)
        with hold_managed_gpu_services(
            required_urls=[
                str(request.get("submit_endpoint") or ""),
                str(request.get("query_endpoint") or ""),
            ],
            reason="heygem_render",
        ):
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                results = []
                for segment in segments:
                    try:
                        results.append(
                            self._execute_segment(
                                client=client,
                                headers=headers,
                                request=request,
                                presenter_source=presenter_source,
                                segment=segment,
                            )
                        )
                    except Exception as exc:
                        results.append(
                            {
                                "segment_id": segment.get("segment_id"),
                                "status": "failed",
                                "error": str(exc),
                            }
                        )

        success_count = sum(1 for item in results if item.get("status") == "success")
        failed_count = sum(1 for item in results if item.get("status") == "failed")
        status = "success"
        if success_count == 0 and failed_count:
            status = "failed"
        elif failed_count:
            status = "partial"
        return {
            "provider": "heygem",
            "job_id": job_id,
            "status": status,
            "presenter_source": presenter_source,
            "segment_count": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "segments": results,
        }

    def _execute_segment(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        request: dict[str, Any],
        presenter_source: str,
        segment: dict[str, Any],
    ) -> dict[str, Any]:
        job_id = str(request.get("job_id") or "").strip()
        segment_id = str(segment.get("segment_id") or "").strip()
        audio_source = _resolve_audio_source(
            str(segment.get("audio_url") or "").strip(),
            job_id=job_id,
            segment_id=segment_id,
        )
        if not audio_source:
            return {
                "segment_id": segment.get("segment_id"),
                "status": "failed",
                "error": "missing_audio_url",
            }

        task_code = f"{segment.get('segment_id') or 'avatar'}-{uuid.uuid4().hex[:10]}"
        payload = {
            "audio_url": audio_source,
            "video_url": presenter_source,
            "code": task_code,
            "watermark_switch": 0,
            "digital_auth": 0,
            "chaofen": 0,
            "pn": 1,
        }
        submit_endpoints = _build_heygem_endpoints(str(request["submit_endpoint"]))
        if not submit_endpoints:
            raise RuntimeError(
                f"heygem submit failed: endpoint {request.get('submit_endpoint')} is training-only and does not expose preview APIs"
            )
        last_error: Exception | None = None
        for endpoints in submit_endpoints:
            task_started = False
            busy_waited_seconds = 0.0
            busy_attempt = 0
            try:
                while True:
                    response = client.post(endpoints["submit"], headers=headers, json=payload)
                    response.raise_for_status()
                    submit_payload = response.json()
                    submit_code = int(submit_payload.get("code") or -1)
                    submit_message = str(submit_payload.get("msg") or "").strip()
                    if submit_code == 10000:
                        break
                    if _is_heygem_busy_message(submit_message):
                        delay = _SEGMENT_BUSY_RETRY_DELAYS_SECONDS[
                            min(busy_attempt, len(_SEGMENT_BUSY_RETRY_DELAYS_SECONDS) - 1)
                        ]
                        if busy_waited_seconds + delay > _SEGMENT_BUSY_MAX_WAIT_SECONDS:
                            return {
                                "segment_id": segment.get("segment_id"),
                                "status": "failed",
                                "task_code": task_code,
                                "error": submit_message or "submit_failed",
                                "response": submit_payload,
                            }
                        busy_attempt += 1
                        busy_waited_seconds += delay
                        time.sleep(delay)
                        continue
                    return {
                        "segment_id": segment.get("segment_id"),
                        "status": "failed",
                        "task_code": task_code,
                        "error": submit_message or "submit_failed",
                        "response": submit_payload,
                    }

                task_started = True
                query_payload = self._poll_task(
                    client=client,
                    headers=headers,
                    query_endpoint=str(endpoints["query"]),
                    task_code=task_code,
                    timeout_seconds=_resolve_task_timeout_seconds(segment),
                )
                data = query_payload.get("data") or {}
                result_value = str(data.get("result") or "").strip()
                local_result_path = _resolve_local_result_path(result_value)
                is_completed = int(data.get("status") or 0) == 2 or _is_completed_task_payload(data)
                ready_local_result_path = (
                    _wait_for_result_file_ready(local_result_path) if is_completed and local_result_path else None
                )
                return {
                    "segment_id": segment.get("segment_id"),
                    "status": "success" if is_completed and ready_local_result_path else "failed",
                    "task_code": task_code,
                    "progress": data.get("progress"),
                    "result": result_value,
                    "local_result_path": ready_local_result_path,
                    "staged_audio_path": _resolve_container_local_path(audio_source),
                    "staged_presenter_path": _resolve_container_local_path(presenter_source),
                    "video_duration": data.get("video_duration"),
                    "width": data.get("width"),
                    "height": data.get("height"),
                    "raw": query_payload,
                }
            except Exception as exc:
                if task_started:
                    raise RuntimeError(
                        f"heygem task failed from {endpoints['submit']}->{endpoints['query']}: {exc}"
                    ) from exc
                last_error = exc
                continue

        if last_error is None:
            raise RuntimeError(f"heygem submit failed for segment {segment.get('segment_id')}")
        available_endpoints = [f"{item['submit']}->{item['query']}" for item in submit_endpoints]
        raise RuntimeError(
            f"heygem submit failed; tried={', '.join(available_endpoints)}; segment={segment.get('segment_id')}; last_error={last_error}"
        ) from last_error


    def _poll_task(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        query_endpoint: str,
        task_code: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        resolved_timeout = max(_TASK_TIMEOUT_MIN_SECONDS, float(timeout_seconds or _TASK_TIMEOUT_MIN_SECONDS))
        resolved_timeout = min(resolved_timeout, _TASK_TIMEOUT_MAX_SECONDS)
        while time.monotonic() - started_at < resolved_timeout:
            response = client.get(query_endpoint, headers=headers, params={"code": task_code})
            response.raise_for_status()
            payload = response.json()
            payload_code = int(payload.get("code") or 0)
            if payload_code == 10004:
                completed_result = _resolve_completed_task_result(task_code)
                if completed_result:
                    return {
                        "code": 10000,
                        "msg": payload.get("msg") or "任务已完成",
                        "data": {
                            "status": 2,
                            "result": f"/{Path(completed_result).name}",
                        },
                    }
            if payload_code not in (0, 10000):
                raise RuntimeError(payload.get("msg") or f"HeyGem task failed: {task_code}")
            data = payload.get("data") or {}
            status_value = int(data.get("status") or 0)
            if status_value == 2 or _is_completed_task_payload(data):
                return payload
            if status_value == 3:
                raise RuntimeError(payload.get("msg") or data.get("msg") or f"HeyGem task failed: {task_code}")
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"HeyGem task timed out: {task_code}")


def _resolve_task_timeout_seconds(segment: dict[str, Any]) -> float:
    duration_sec = max(0.0, float(segment.get("duration_sec") or 0.0))
    scaled_timeout = duration_sec * _TASK_TIMEOUT_AUDIO_RATIO + _TASK_TIMEOUT_BUFFER_SECONDS
    return min(_TASK_TIMEOUT_MAX_SECONDS, max(_TASK_TIMEOUT_MIN_SECONDS, scaled_timeout))


def _is_completed_task_payload(data: dict[str, Any]) -> bool:
    result = str(data.get("result") or "").strip()
    if not result:
        return False
    progress = data.get("progress")
    try:
        progress_value = float(progress)
    except (TypeError, ValueError):
        progress_value = None
    status_value = int(data.get("status") or 0)
    return status_value == 1 and progress_value is not None and progress_value >= 100.0


def _is_heygem_busy_message(message: object) -> bool:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    busy_tokens = (
        "busy",
        "resource busy",
        "device busy",
        "繁忙",
        "忙碌",
        "稍后",
        "请稍后",
    )
    return any(token in normalized for token in busy_tokens)


def _build_heygem_endpoints(submit_like_url: str) -> list[dict[str, str]]:
    raw = str(submit_like_url or "").strip().rstrip("/")
    base = raw
    for suffix in ("/easy/submit", "/easy/query", "/v1/submit", "/v1/query", "/api/submit", "/api/query", "/submit", "/query"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = base.rstrip("/")

    if _is_training_only_endpoint(base):
        return []

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
            endpoints.append({"submit": submit_url, "query": f"{base}{query_suffix}"})
    return endpoints


def _is_training_only_endpoint(base: str) -> bool:
    normalized_base = str(base or "").strip().rstrip("/")
    if not normalized_base:
        return False
    if normalized_base in _HEYGEM_PREVIEW_SERVICE_CACHE:
        return _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base]

    timeout = httpx.Timeout(_HEYGEM_TRAINING_PROBE_TIMEOUT_SECONDS, connect=1.0)
    try:
        with httpx.Client(timeout=timeout) as probe_client:
            response = probe_client.get(f"{normalized_base}/json")
            response.raise_for_status()
            openapi_spec = response.json()
    except Exception:
        for preview_path in ("/easy/query?code=healthcheck", "/v1/easy/query?code=healthcheck", "/query?code=healthcheck"):
            try:
                preview_response = httpx.get(f"{normalized_base}{preview_path}", timeout=timeout)
                if preview_response.status_code < 500:
                    _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = False
                    return False
            except Exception:
                continue
        try:
            training_response = httpx.post(f"{normalized_base}/v1/health", timeout=timeout)
            if training_response.status_code < 500:
                _HEYGEM_PREVIEW_SERVICE_CACHE[normalized_base] = True
                return True
        except Exception:
            return False
        return False

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


def _resolve_presenter_source(presenter_id: str, *, job_id: str | None = None) -> str | None:
    if presenter_id.startswith(("http://", "https://")):
        return presenter_id

    shared_root = _detect_shared_root()
    if shared_root is None:
        return presenter_id if Path(presenter_id).exists() else None

    shared_video_dir = shared_root / "inputs" / "video"
    shared_video_dir.mkdir(parents=True, exist_ok=True)

    local_path = Path(presenter_id)
    if local_path.exists():
        if job_id:
            target_path = _prepare_presenter_video(
                local_path=local_path,
                shared_video_dir=shared_video_dir,
                job_id=job_id,
            )
        else:
            target_path = _prepare_presenter_video(local_path=local_path, shared_video_dir=shared_video_dir)
        return _shared_video_url(target_path.name)

    if presenter_id.startswith("/code/data/inputs/video/"):
        return presenter_id

    existing_shared = shared_video_dir / presenter_id
    if existing_shared.exists():
        return _shared_video_url(existing_shared.name)

    return None


def _prepare_presenter_video(*, local_path: Path, shared_video_dir: Path, job_id: str | None = None) -> Path:
    safe_stem = local_path.stem or "avatar_anchor"
    prefix = _normalize_job_path_prefix(job_id)
    target_name = f"{safe_stem}_heygem_anchor.mp4"
    if prefix:
        target_name = f"{prefix}_{target_name}"
    target_path = shared_video_dir / target_name
    if target_path.exists() and target_path.stat().st_mtime >= local_path.stat().st_mtime:
        return target_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(local_path),
        "-an",
        "-vf",
        "fps=25,format=yuv420p",
        "-r",
        "25",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(target_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to prepare heygem presenter video: {result.stderr[-2000:]}")
    return target_path


def _resolve_local_result_path(result_value: str) -> str | None:
    if not result_value:
        return None
    direct_path = Path(str(result_value))
    if direct_path.exists():
        return str(direct_path)
    shared_root = _detect_shared_root()
    if shared_root is None:
        return None
    normalized = str(result_value).strip().replace("\\", "/")
    relative_candidates: list[str] = []
    if normalized.startswith("/code/data/"):
        relative_candidates.append(normalized.removeprefix("/code/data/").lstrip("/"))
    relative_candidates.append(normalized.lstrip("/"))
    candidate_paths = [
        candidate
        for relative_value in relative_candidates
        for candidate in (
            shared_root / relative_value,
            shared_root / "temp" / relative_value,
            shared_root / "result" / relative_value,
        )
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return str(candidate)
    return None


def _resolve_completed_task_result(task_code: str) -> str | None:
    if not task_code:
        return None
    return _resolve_local_result_path(f"/{task_code}-r.mp4")


def _resolve_audio_source(
    audio_value: str,
    *,
    job_id: str | None = None,
    segment_id: str | None = None,
) -> str | None:
    if not audio_value:
        return None
    if audio_value.startswith(("http://", "https://")):
        return audio_value
    if audio_value.startswith("/code/data/inputs/audio/"):
        return audio_value

    shared_root = _detect_shared_root()
    local_path = Path(audio_value)
    if shared_root is None:
        return str(local_path) if local_path.exists() else None
    if not local_path.exists():
        return None

    shared_audio_dir = shared_root / "inputs" / "audio"
    shared_audio_dir.mkdir(parents=True, exist_ok=True)
    prefix_parts = [part for part in (_normalize_job_path_prefix(job_id), _sanitize_stage_name(segment_id)) if part]
    target_name = local_path.name if not prefix_parts else f"{'_'.join(prefix_parts)}_{local_path.name}"
    target_path = shared_audio_dir / target_name
    _stage_audio_file(local_path=local_path, target_path=target_path)
    return str((Path("/code/data/inputs/audio") / target_path.name).as_posix())


def _stage_audio_file(*, local_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.resolve() == target_path.resolve():
        if _wait_for_staged_audio_ready(target_path) is None:
            _rewrite_audio_to_staged_wav(source_path=local_path, target_path=target_path)
        if _wait_for_staged_audio_ready(target_path) is None:
            raise RuntimeError(f"staged_audio_unreadable: {target_path}")
        _settle_shared_audio_mount(target_path)
        return

    temp_target = target_path.with_name(f"{target_path.name}.{uuid.uuid4().hex}.partial")
    try:
        shutil.copy2(local_path, temp_target)
        if _wait_for_staged_audio_ready(temp_target) is None:
            try:
                _rewrite_audio_to_staged_wav(source_path=local_path, target_path=temp_target)
            except RuntimeError:
                pass
            if _wait_for_staged_audio_ready(temp_target) is None:
                raise RuntimeError(f"staged_audio_unreadable: {target_path}")
        os.replace(temp_target, target_path)
    finally:
        if temp_target.exists():
            temp_target.unlink(missing_ok=True)

    if _wait_for_staged_audio_ready(target_path) is None:
        try:
            _rewrite_audio_to_staged_wav(source_path=local_path, target_path=target_path)
        except RuntimeError:
            pass
    if _wait_for_staged_audio_ready(target_path) is None:
        raise RuntimeError(f"staged_audio_unreadable: {target_path}")
    _settle_shared_audio_mount(target_path)


def _rewrite_audio_to_staged_wav(*, source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(target_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr = str(result.stderr or "").strip()
        raise RuntimeError(f"failed to normalize staged audio: {stderr[-2000:]}")


def _probe_audio_duration_seconds(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(str(result.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return duration


def _wait_for_staged_audio_ready(path: Path) -> float | None:
    for attempt in range(_SHARED_AUDIO_READY_RETRIES):
        duration = _probe_audio_duration_seconds(path)
        if duration is not None:
            return duration
        if attempt + 1 < _SHARED_AUDIO_READY_RETRIES:
            time.sleep(_SHARED_AUDIO_READY_RETRY_SECONDS)
    return None


def _wait_for_result_file_ready(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    for attempt in range(_RESULT_READY_RETRIES):
        try:
            if path.exists() and path.stat().st_size > 0:
                return str(path)
        except OSError:
            pass
        if attempt + 1 < _RESULT_READY_RETRIES:
            time.sleep(_RESULT_READY_RETRY_SECONDS)
    return None


def _settle_shared_audio_mount(path: Path) -> None:
    try:
        size_bytes = max(0, int(path.stat().st_size))
    except OSError:
        return
    # Docker Desktop bind mounts can briefly expose a just-written file before the
    # guest sees the final contents. Keep the final name hidden until replace, then
    # pause for a short size-based window before submitting to HeyGem.
    settle_seconds = min(
        _SHARED_AUDIO_SETTLE_MAX_SECONDS,
        max(_SHARED_AUDIO_SETTLE_FLOOR_SECONDS, size_bytes / _SHARED_AUDIO_SETTLE_BYTES_PER_SECOND),
    )
    time.sleep(settle_seconds)


def _detect_shared_root() -> Path | None:
    configured_root = _resolve_docker_configured_shared_root()
    if configured_root is not None:
        return configured_root
    env_root = os.getenv("HEYGEM_SHARED_ROOT")
    env_host_root = os.getenv("HEYGEM_SHARED_HOST_DIR")
    if env_root or env_host_root:
        return resolve_heygem_shared_root()
    for root in _DEFAULT_SHARED_ROOTS:
        if root.exists():
            return root
    return None


def _resolve_docker_configured_shared_root() -> Path | None:
    settings = get_settings()
    env_file = Path(str(getattr(settings, "heygem_docker_env_file", "") or "")).expanduser()
    if not env_file.exists():
        return None
    raw_data_dir = _read_env_file_value(env_file, "HEYGEM_DATA_DIR")
    if not raw_data_dir:
        return None
    candidate = Path(raw_data_dir).expanduser()
    return candidate if candidate.exists() else None


def _read_env_file_value(path: Path, key: str) -> str | None:
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            current_key, value = line.split("=", 1)
            if current_key.strip() != key:
                continue
            cleaned = value.strip().strip('"').strip("'")
            return cleaned or None
    except OSError:
        return None
    return None


def _shared_video_url(name: str) -> str:
    return str((_CONTAINER_VIDEO_ROOT / name).as_posix())


def _resolve_container_local_path(container_path: str) -> str | None:
    value = str(container_path or "").strip()
    if not value.startswith("/code/data/"):
        return None
    shared_root = _detect_shared_root()
    if shared_root is None:
        return None
    relative = value.removeprefix("/code/data/").replace("/", "\\")
    return str((shared_root / relative).resolve())


def _normalize_job_path_prefix(job_id: str | None) -> str:
    raw = str(job_id or "").strip().replace("-", "_")
    return raw[:48].strip("._")


def _sanitize_stage_name(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)[:48].strip("._")
