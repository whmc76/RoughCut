from __future__ import annotations

import shutil
import subprocess
import time
import uuid
import os
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import DEFAULT_HEYGEM_SHARED_ROOT, get_settings, resolve_heygem_shared_root
from roughcut.docker_gpu_guard import hold_managed_gpu_services
from roughcut.providers.avatar.base import AvatarProvider
from roughcut.runtime_paths import resolve_runtime_media_path

_DEFAULT_SHARED_ROOTS = (
    DEFAULT_HEYGEM_SHARED_ROOT,
)
_CONTAINER_VIDEO_ROOT = Path("/code/data/inputs/video")
_CONTAINER_AUDIO_ROOT = Path("/code/data/inputs/audio")
_CONTAINER_RESULT_ROOT = Path("/code/data/result")
_POLL_INTERVAL_SECONDS = 2.0
_TASK_TIMEOUT_MIN_SECONDS = 600.0
_TASK_TIMEOUT_MAX_SECONDS = 3600.0
_TASK_TIMEOUT_AUDIO_RATIO = 3.0
_TASK_TIMEOUT_BUFFER_SECONDS = 180.0
_TASK_NO_PROGRESS_TIMEOUT_SECONDS = 0.0
_HEYGEM_TRAINING_PROBE_TIMEOUT_SECONDS = 2.0
_HEYGEM_PREVIEW_SERVICE_CACHE: dict[str, bool] = {}
_SHARED_AUDIO_READY_RETRIES = 12
_SHARED_AUDIO_READY_RETRY_SECONDS = 1.0
_SHARED_AUDIO_SETTLE_FLOOR_SECONDS = 0.5
_SHARED_AUDIO_SETTLE_MAX_SECONDS = 8.0
_SHARED_AUDIO_SETTLE_BYTES_PER_SECOND = 8 * 1024 * 1024
_SEGMENT_BUSY_RETRY_DELAYS_SECONDS = (2.0, 4.0, 6.0, 8.0, 10.0)
_SEGMENT_BUSY_MAX_WAIT_SECONDS = 300.0
_RESULT_READY_RETRIES = 30
_RESULT_READY_RETRY_SECONDS = 2.0

logger = logging.getLogger(__name__)


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
            "presenter_id": plan.get("presenter_id"),
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
                    segment_presenter_source = presenter_source
                    segment_presenter_id = str(segment.get("presenter_id") or "").strip()
                    if segment_presenter_id:
                        resolved_segment_presenter = _resolve_presenter_source(segment_presenter_id, job_id=job_id)
                        if not resolved_segment_presenter:
                            results.append(
                                {
                                    "segment_id": segment.get("segment_id"),
                                    "status": "failed",
                                    "error": "presenter_source_not_found",
                                    "presenter_id": segment_presenter_id,
                                }
                            )
                            continue
                        segment_presenter_source = resolved_segment_presenter
                    try:
                        results.append(
                            self._execute_segment(
                                client=client,
                                headers=headers,
                                request=request,
                                presenter_source=segment_presenter_source,
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

    def estimate_render_timeout_seconds(self, *, request: dict[str, Any]) -> float | None:
        segments = list(request.get("segments") or [])
        if not segments:
            return _TASK_TIMEOUT_MIN_SECONDS
        return float(sum(_resolve_task_timeout_seconds(segment) for segment in segments))

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
        _ensure_heygem_container_path_visible(audio_source, media_kind="audio")
        _ensure_heygem_container_path_visible(presenter_source, media_kind="video")
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
            busy_max_wait_seconds = _resolve_segment_busy_max_wait_seconds()
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
                        if busy_waited_seconds + delay > busy_max_wait_seconds:
                            return {
                                "segment_id": segment.get("segment_id"),
                                "status": "failed",
                                "task_code": task_code,
                                "error": submit_message or "submit_failed",
                                "response": submit_payload,
                            }
                        busy_attempt += 1
                        busy_waited_seconds += delay
                        logger.warning(
                            "HeyGem segment submit busy segment_id=%s task_code=%s waited=%.1fs/%.1fs delay=%.1fs code=%s msg=%s",
                            segment.get("segment_id"),
                            task_code,
                            busy_waited_seconds,
                            busy_max_wait_seconds,
                            delay,
                            submit_code,
                            submit_message,
                        )
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
                is_completed = int(data.get("status") or 0) == 2 or _is_completed_task_payload(data)
                local_result_path = (
                    _resolve_or_collect_result_path(
                        result_value,
                        task_code=task_code,
                        min_duration_sec=_segment_expected_duration_seconds(segment),
                    )
                    if is_completed
                    else None
                )
                ready_local_result_path = (
                    _wait_for_result_file_ready(local_result_path) if is_completed and local_result_path else None
                )
                if is_completed and ready_local_result_path:
                    _cleanup_heygem_task_artifacts(
                        task_code=task_code,
                        result_value=result_value,
                        preserved_paths=[ready_local_result_path],
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
        no_progress_timeout = _resolve_task_no_progress_timeout_seconds()
        last_progress_marker: tuple[int, str, str, str] | None = None
        last_progress_at = started_at
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
            now = time.monotonic()
            progress_marker = (
                status_value,
                str(data.get("progress") or ""),
                str(data.get("msg") or payload.get("msg") or ""),
                str(data.get("result") or ""),
            )
            if progress_marker != last_progress_marker:
                last_progress_marker = progress_marker
                last_progress_at = now
            elif no_progress_timeout is not None and now - last_progress_at >= no_progress_timeout:
                raise TimeoutError(f"HeyGem task made no progress for {no_progress_timeout:.0f}s: {task_code}")
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"HeyGem task timed out: {task_code}")


def _resolve_task_no_progress_timeout_seconds() -> float | None:
    try:
        configured = float(
            getattr(
                get_settings(),
                "avatar_render_no_progress_timeout_sec",
                _TASK_NO_PROGRESS_TIMEOUT_SECONDS,
            )
            or _TASK_NO_PROGRESS_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        configured = _TASK_NO_PROGRESS_TIMEOUT_SECONDS
    if configured <= 0:
        return None
    return min(_TASK_TIMEOUT_MAX_SECONDS, max(60.0, configured))


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


def _resolve_segment_busy_max_wait_seconds() -> float:
    raw_value = os.getenv("ROUGHCUT_HEYGEM_SEGMENT_BUSY_MAX_WAIT_SECONDS", str(_SEGMENT_BUSY_MAX_WAIT_SECONDS)).strip()
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return float(_SEGMENT_BUSY_MAX_WAIT_SECONDS)
    return max(30.0, min(900.0, value))


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

    local_path = resolve_runtime_media_path(presenter_id)
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


def _resolve_or_collect_result_path(
    result_value: str,
    *,
    task_code: str | None = None,
    min_duration_sec: float | None = None,
) -> str | None:
    local_result = _resolve_local_result_path(result_value)
    if local_result and _local_video_duration_satisfies(local_result, min_duration_sec=min_duration_sec):
        collected = _copy_local_heygem_result_to_collected(
            local_result,
            task_code=task_code,
            min_duration_sec=min_duration_sec,
        )
        return collected or local_result
    for attempt in range(_RESULT_READY_RETRIES):
        for container_path in _candidate_heygem_result_container_paths(result_value, task_code=task_code):
            collected = _collect_heygem_container_result(
                container_path,
                task_code=task_code,
                min_duration_sec=min_duration_sec,
            )
            if collected:
                return collected
        if attempt + 1 < _RESULT_READY_RETRIES:
            time.sleep(_RESULT_READY_RETRY_SECONDS)
    return None


def _candidate_heygem_result_container_paths(result_value: str, *, task_code: str | None = None) -> list[str]:
    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip().replace("\\", "/")
        if not normalized:
            return
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        if not normalized.startswith("/code/data/"):
            normalized = f"/code/data{normalized}"
        if normalized not in candidates:
            candidates.append(normalized)

    safe_task_code = str(task_code or "").strip()
    if safe_task_code:
        add(f"/{safe_task_code}-r.mp4")
        add(f"/result/{safe_task_code}-r.mp4")
        add(f"/temp/{safe_task_code}/result.avi")
        add(f"/temp/{safe_task_code}/result.mp4")

    normalized_result = str(result_value or "").strip().replace("\\", "/")
    if normalized_result:
        add(normalized_result)
        if not normalized_result.startswith("/"):
            add(f"/temp/{normalized_result}")
            add(f"/result/{normalized_result}")
        elif not normalized_result.startswith("/code/data/"):
            add(f"/temp/{normalized_result.lstrip('/')}")
            add(f"/result/{normalized_result.lstrip('/')}")
    return candidates


def _collect_heygem_container_result(
    container_path: str,
    *,
    task_code: str | None = None,
    min_duration_sec: float | None = None,
) -> str | None:
    value = str(container_path or "").strip()
    if not value.startswith("/code/data/"):
        return None
    container_name = _resolve_running_heygem_container_name()
    if not container_name:
        return None
    if not _heygem_container_file_ready(container_name=container_name, container_path=value, media_kind="video"):
        return None
    if not _container_video_duration_satisfies(
        container_name=container_name,
        container_path=value,
        min_duration_sec=min_duration_sec,
    ):
        return None
    shared_root = _detect_shared_root()
    if shared_root is None:
        return None
    safe_task_code = _sanitize_stage_name(task_code or Path(value).parent.name or "heygem_result")
    suffix = Path(value).suffix or ".mp4"
    target_dir = shared_root / "result" / "roughcut_collected"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_task_code}_{Path(value).stem or 'result'}{suffix}"
    copy_result = _run_docker_command(
        ["docker", "cp", f"{container_name}:{value}", str(target_path)],
        timeout=300.0,
    )
    if copy_result is None or copy_result.returncode != 0:
        return None
    ready_path = _wait_for_result_file_ready(str(target_path))
    if not ready_path or not _local_video_duration_satisfies(ready_path, min_duration_sec=min_duration_sec):
        return None
    return ready_path


def _copy_local_heygem_result_to_collected(
    local_result: str,
    *,
    task_code: str | None = None,
    min_duration_sec: float | None = None,
) -> str | None:
    source_path = Path(str(local_result or "")).expanduser()
    if not source_path.exists():
        return None
    shared_root = _detect_shared_root()
    if shared_root is None:
        return None
    try:
        source_resolved = source_path.resolve()
        shared_resolved = shared_root.resolve()
        source_resolved.relative_to(shared_resolved)
    except Exception:
        return None

    target_root = (shared_root / "result" / "roughcut_collected").resolve()
    if _is_relative_to(source_resolved, target_root):
        return str(source_resolved)

    safe_task_code = _sanitize_stage_name(task_code or source_path.parent.name or "heygem_result")
    suffix = source_path.suffix or ".mp4"
    target_root.mkdir(parents=True, exist_ok=True)
    target_path = target_root / f"{safe_task_code}_{source_path.stem or 'result'}{suffix}"
    if source_resolved != target_path.resolve():
        shutil.copy2(source_resolved, target_path)
    ready_path = _wait_for_result_file_ready(str(target_path))
    if not ready_path or not _local_video_duration_satisfies(ready_path, min_duration_sec=min_duration_sec):
        return None
    return ready_path


def _cleanup_heygem_task_artifacts(
    *,
    task_code: str,
    result_value: str | None = None,
    preserved_paths: list[str] | tuple[str, ...] | None = None,
) -> None:
    shared_root = _detect_shared_root()
    safe_task_code = _sanitize_stage_name(task_code)
    if shared_root is None or not safe_task_code:
        return
    try:
        shared_resolved = shared_root.resolve()
    except Exception:
        return
    preserved: set[Path] = set()
    for value in preserved_paths or []:
        try:
            preserved.add(Path(str(value)).expanduser().resolve())
        except Exception:
            continue

    candidates: list[Path] = [
        shared_root / "temp" / safe_task_code,
        shared_root / f"{safe_task_code}-r.mp4",
        shared_root / "result" / f"{safe_task_code}-r.mp4",
    ]
    local_result = _resolve_local_result_path(str(result_value or ""))
    if local_result:
        candidates.append(Path(local_result))

    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
            resolved.relative_to(shared_resolved)
        except Exception:
            continue
        if resolved in preserved or any(_is_relative_to(keep, resolved) for keep in preserved):
            continue
        if _is_relative_to(resolved, (shared_root / "result" / "roughcut_collected").resolve()):
            continue
        if not (
            _is_relative_to(resolved, (shared_root / "temp").resolve())
            or _is_relative_to(resolved, (shared_root / "result").resolve())
            or resolved.parent == shared_resolved
        ):
            continue
        try:
            if resolved.is_dir():
                shutil.rmtree(resolved, ignore_errors=True)
            else:
                resolved.unlink(missing_ok=True)
        except OSError:
            continue


def _resolve_completed_task_result(task_code: str) -> str | None:
    if not task_code:
        return None
    return _resolve_or_collect_result_path("", task_code=task_code)


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
    local_path = resolve_runtime_media_path(audio_value)
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
    return str((_CONTAINER_AUDIO_ROOT / target_path.name).as_posix())


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


def _segment_expected_duration_seconds(segment: dict[str, Any]) -> float | None:
    try:
        value = float(segment.get("duration_sec") or 0.0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _container_video_duration_satisfies(
    *,
    container_name: str,
    container_path: str,
    min_duration_sec: float | None,
) -> bool:
    if min_duration_sec is None or min_duration_sec <= 0:
        return True
    duration = _probe_heygem_container_video_duration_seconds(
        container_name=container_name,
        container_path=container_path,
    )
    return duration is not None and duration + 1.0 >= min_duration_sec


def _local_video_duration_satisfies(path_value: str, *, min_duration_sec: float | None) -> bool:
    if min_duration_sec is None or min_duration_sec <= 0:
        return True
    duration = _probe_local_video_duration_seconds(path_value)
    return duration is not None and duration + 1.0 >= min_duration_sec


def _probe_heygem_container_video_duration_seconds(*, container_name: str, container_path: str) -> float | None:
    result = _run_docker_command(
        [
            "docker",
            "exec",
            container_name,
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,nb_read_frames,avg_frame_rate,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            container_path,
        ],
        timeout=45.0,
    )
    if result is None or result.returncode != 0:
        return None
    return _duration_from_ffprobe_json(str(result.stdout or ""))


def _probe_local_video_duration_seconds(path_value: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration,nb_read_frames,avg_frame_rate,r_frame_rate",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path_value),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _duration_from_ffprobe_json(str(result.stdout or ""))


def _duration_from_ffprobe_json(payload_value: str) -> float | None:
    try:
        payload = json.loads(payload_value)
    except (TypeError, ValueError):
        return None
    format_duration = _positive_float(((payload.get("format") or {}) if isinstance(payload, dict) else {}).get("duration"))
    if format_duration is not None:
        return format_duration
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list) or not streams:
        return None
    stream = streams[0] if isinstance(streams[0], dict) else {}
    stream_duration = _positive_float(stream.get("duration"))
    if stream_duration is not None:
        return stream_duration
    frame_count = _positive_float(stream.get("nb_read_frames"))
    frame_rate = _parse_frame_rate(str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""))
    if frame_count is None or frame_rate is None or frame_rate <= 0:
        return None
    return frame_count / frame_rate


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_frame_rate(value: str) -> float | None:
    raw = str(value or "").strip()
    if not raw or raw == "0/0":
        return None
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        numerator_value = _positive_float(numerator)
        denominator_value = _positive_float(denominator)
        if numerator_value is None or denominator_value is None:
            return None
        return numerator_value / denominator_value
    return _positive_float(raw)


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
    # HeyGem is a shared service outside RoughCut. Resolve its public data root
    # from the HeyGem service env first so RoughCut only stages files into the
    # shared mount that the running HeyGem container actually sees.
    configured_root = _resolve_docker_configured_shared_root()
    if configured_root is not None:
        return configured_root
    env_data_dir = os.getenv("HEYGEM_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir).expanduser()
    env_root = os.getenv("HEYGEM_SHARED_ROOT")
    env_host_root = os.getenv("HEYGEM_SHARED_HOST_DIR")
    if env_root or env_host_root:
        return resolve_heygem_shared_root()
    for root in _DEFAULT_SHARED_ROOTS:
        if root.exists():
            return root
    return None


def _candidate_heygem_container_names() -> list[str]:
    candidates: list[str] = []
    try:
        service_names = str(getattr(get_settings(), "heygem_docker_services", "") or "")
    except Exception:
        service_names = ""
    for value in service_names.replace(",", " ").split():
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    for fallback in ("heygem", "roughcut-heygem-1"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _resolve_running_heygem_container_name() -> str | None:
    for name in _candidate_heygem_container_names():
        result = _run_docker_command(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            timeout=5.0,
        )
        if result is not None and result.returncode == 0 and str(result.stdout or "").strip().lower() == "true":
            return name
    return None


def _ensure_heygem_container_path_visible(container_path: str, *, media_kind: str) -> None:
    value = str(container_path or "").strip()
    if not value.startswith("/code/data/"):
        return
    container_name = _resolve_running_heygem_container_name()
    if not container_name:
        return
    if _heygem_container_file_ready(container_name=container_name, container_path=value, media_kind=media_kind):
        return

    local_path_value = _resolve_container_local_path(value)
    if not local_path_value:
        raise RuntimeError(f"heygem_shared_file_not_staged:{value}")
    local_path = Path(local_path_value)
    if not local_path.exists():
        raise RuntimeError(f"heygem_shared_file_not_staged:{local_path}")

    parent_path = str(Path(value).parent.as_posix())
    mkdir_result = _run_docker_command(
        ["docker", "exec", container_name, "mkdir", "-p", parent_path],
        timeout=10.0,
    )
    if mkdir_result is None or mkdir_result.returncode != 0:
        detail = str(getattr(mkdir_result, "stderr", "") or "").strip() if mkdir_result is not None else "docker unavailable"
        raise RuntimeError(f"heygem_shared_mount_prepare_failed:{value}:{detail[-500:]}")

    copy_result = _run_docker_command(
        ["docker", "cp", str(local_path), f"{container_name}:{value}"],
        timeout=120.0,
    )
    if copy_result is None or copy_result.returncode != 0:
        detail = str(getattr(copy_result, "stderr", "") or "").strip() if copy_result is not None else "docker unavailable"
        raise RuntimeError(f"heygem_shared_mount_sync_failed:{value}:{detail[-500:]}")
    if not _heygem_container_file_ready(container_name=container_name, container_path=value, media_kind=media_kind):
        raise RuntimeError(f"heygem_shared_mount_sync_unreadable:{value}")


def _heygem_container_file_ready(*, container_name: str, container_path: str, media_kind: str) -> bool:
    if media_kind == "audio":
        result = _run_docker_command(
            [
                "docker",
                "exec",
                container_name,
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                container_path,
            ],
            timeout=15.0,
        )
        if result is None or result.returncode != 0:
            return False
        try:
            return float(str(result.stdout or "").strip()) > 0
        except (TypeError, ValueError):
            return False
    result = _run_docker_command(
        ["docker", "exec", container_name, "test", "-s", container_path],
        timeout=10.0,
    )
    return result is not None and result.returncode == 0


def _run_docker_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
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
    relative = value.removeprefix("/code/data/").lstrip("/").replace("\\", "/")
    return str((shared_root / Path(relative)).resolve())


def _normalize_job_path_prefix(job_id: str | None) -> str:
    raw = str(job_id or "").strip().replace("-", "_")
    return raw[:48].strip("._")


def _sanitize_stage_name(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)[:48].strip("._")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
