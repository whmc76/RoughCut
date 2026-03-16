from __future__ import annotations

import shutil
import subprocess
import time
import uuid
import os
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services
from roughcut.providers.avatar.base import AvatarProvider

_DEFAULT_SHARED_ROOTS = (
    Path("E:/WorkSpace/heygem/data"),
    Path("D:/duix_avatar_data/face2face"),
    Path("d:/duix_avatar_data/face2face"),
    Path("data/heygem"),
)
_CONTAINER_VIDEO_ROOT = Path("/code/data/inputs/video")
_POLL_INTERVAL_SECONDS = 2.0
_TASK_TIMEOUT_MIN_SECONDS = 600.0
_TASK_TIMEOUT_MAX_SECONDS = 3600.0
_TASK_TIMEOUT_AUDIO_RATIO = 3.0
_TASK_TIMEOUT_BUFFER_SECONDS = 180.0
_HEYGEM_TRAINING_PROBE_TIMEOUT_SECONDS = 2.0
_HEYGEM_PREVIEW_SERVICE_CACHE: dict[str, bool] = {}


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

        presenter_source = _resolve_presenter_source(presenter_id)
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
        audio_source = _resolve_audio_source(str(segment.get("audio_url") or "").strip())
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
            try:
                response = client.post(endpoints["submit"], headers=headers, json=payload)
                response.raise_for_status()
                submit_payload = response.json()
                submit_code = int(submit_payload.get("code") or -1)
                if submit_code != 10000:
                    return {
                        "segment_id": segment.get("segment_id"),
                        "status": "failed",
                        "task_code": task_code,
                        "error": submit_payload.get("msg") or "submit_failed",
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
                return {
                    "segment_id": segment.get("segment_id"),
                    "status": "success" if int(data.get("status") or 0) == 2 else "failed",
                    "task_code": task_code,
                    "progress": data.get("progress"),
                    "result": result_value,
                    "local_result_path": _resolve_local_result_path(result_value),
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
            if status_value == 2:
                return payload
            if status_value == 3:
                raise RuntimeError(payload.get("msg") or data.get("msg") or f"HeyGem task failed: {task_code}")
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"HeyGem task timed out: {task_code}")


def _resolve_task_timeout_seconds(segment: dict[str, Any]) -> float:
    duration_sec = max(0.0, float(segment.get("duration_sec") or 0.0))
    scaled_timeout = duration_sec * _TASK_TIMEOUT_AUDIO_RATIO + _TASK_TIMEOUT_BUFFER_SECONDS
    return min(_TASK_TIMEOUT_MAX_SECONDS, max(_TASK_TIMEOUT_MIN_SECONDS, scaled_timeout))


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


def _resolve_presenter_source(presenter_id: str) -> str | None:
    if presenter_id.startswith(("http://", "https://")):
        return presenter_id

    shared_root = _detect_shared_root()
    if shared_root is None:
        return presenter_id if Path(presenter_id).exists() else None

    shared_video_dir = shared_root / "inputs" / "video"
    shared_video_dir.mkdir(parents=True, exist_ok=True)

    local_path = Path(presenter_id)
    if local_path.exists():
        target_path = _prepare_presenter_video(local_path=local_path, shared_video_dir=shared_video_dir)
        return _shared_video_url(target_path.name)

    if presenter_id.startswith("/code/data/inputs/video/"):
        return presenter_id

    existing_shared = shared_video_dir / presenter_id
    if existing_shared.exists():
        return _shared_video_url(existing_shared.name)

    return None


def _prepare_presenter_video(*, local_path: Path, shared_video_dir: Path) -> Path:
    safe_stem = local_path.stem or "avatar_anchor"
    target_path = shared_video_dir / f"{safe_stem}_heygem_anchor.mp4"
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
    shared_root = _detect_shared_root()
    if shared_root is None:
        return None
    candidate_paths = [
        shared_root / "result" / result_value.lstrip("/"),
        shared_root / "temp" / result_value.lstrip("/"),
        shared_root / result_value.lstrip("/"),
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return str(candidate)
    return None


def _resolve_completed_task_result(task_code: str) -> str | None:
    if not task_code:
        return None
    return _resolve_local_result_path(f"/{task_code}-r.mp4")


def _resolve_audio_source(audio_value: str) -> str | None:
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
    target_path = shared_audio_dir / local_path.name
    if local_path.resolve() != target_path.resolve():
        shutil.copy2(local_path, target_path)
    return str((Path("/code/data/inputs/audio") / target_path.name).as_posix())


def _detect_shared_root() -> Path | None:
    env_root = os.getenv("HEYGEM_SHARED_ROOT")
    if env_root:
        env_path = Path(env_root)
        if not env_path.exists():
            env_path.mkdir(parents=True, exist_ok=True)
        return env_path
    for root in _DEFAULT_SHARED_ROOTS:
        if root.exists():
            return root
    return None


def _shared_video_url(name: str) -> str:
    return str((_CONTAINER_VIDEO_ROOT / name).as_posix())
