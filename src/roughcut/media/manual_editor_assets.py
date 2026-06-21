from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import wave
from typing import Any
import uuid

from roughcut.config import get_settings
from roughcut.media.silence import detect_silence

MANUAL_EDITOR_PREVIEW_ARTIFACT_TYPE = "manual_editor_preview_assets"
MANUAL_EDITOR_PREVIEW_ASSET_VERSION = 14
MANUAL_EDITOR_PREVIEW_STATUS_FILENAME = "status.json"
PREVIEW_AUDIO_TARGET_LUFS = -16.0
PREVIEW_AUDIO_MIN_GAIN = 0.35
PREVIEW_AUDIO_MAX_GAIN = 12.0
_VIDEO_PROXY_READY_STAGES = {"proxy_webm", "proxy_audio", "loudness_analysis", "thumbnails", "ready", "cached"}
_WEBM_PROXY_READY_STAGES = {"proxy_audio", "loudness_analysis", "thumbnails", "ready", "cached"}


def manual_editor_asset_dir(job_id: uuid.UUID | str, *, output_project_dir: Path | str | None = None) -> Path:
    if output_project_dir is not None:
        return Path(output_project_dir).expanduser() / "manual-editor"
    root = Path(get_settings().job_storage_dir).expanduser()
    return root / str(job_id) / "manual-editor"


def manual_editor_asset_manifest_path(job_id: uuid.UUID | str, *, asset_dir: Path | str | None = None) -> Path:
    return _resolve_manual_editor_asset_dir(job_id, asset_dir=asset_dir) / "manifest.json"


def manual_editor_asset_status_path(job_id: uuid.UUID | str, *, asset_dir: Path | str | None = None) -> Path:
    return _resolve_manual_editor_asset_dir(job_id, asset_dir=asset_dir) / MANUAL_EDITOR_PREVIEW_STATUS_FILENAME


def _resolve_manual_editor_asset_dir(job_id: uuid.UUID | str, *, asset_dir: Path | str | None = None) -> Path:
    return Path(asset_dir).expanduser() if asset_dir is not None else manual_editor_asset_dir(job_id)


def mark_manual_editor_preview_assets_queued(job_id: uuid.UUID | str, *, asset_dir: Path | str | None = None) -> dict[str, Any]:
    return _write_asset_status(
        _resolve_manual_editor_asset_dir(job_id, asset_dir=asset_dir),
        status="warming",
        stage="queued",
        progress=0.02,
        detail="Preview asset generation queued",
    )


def ensure_manual_editor_preview_assets(
    *,
    job_id: uuid.UUID | str,
    source_path: Path,
    duration_sec: float,
    asset_dir: Path | str | None = None,
    orientation_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_dir = _resolve_manual_editor_asset_dir(job_id, asset_dir=asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    audio_path = asset_dir / "proxy.wav"
    video_path = asset_dir / "proxy.mp4"
    webm_path = asset_dir / "proxy.webm"
    peaks_path = asset_dir / "peaks.json"
    manifest_path = manual_editor_asset_manifest_path(job_id, asset_dir=asset_dir)
    source_fingerprint = _source_fingerprint(source_path)
    normalized_orientation = _normalize_orientation_decision(orientation_decision)
    orientation_fingerprint = _orientation_fingerprint(normalized_orientation)

    manifest = _read_json(manifest_path)
    status_payload = _read_asset_status(asset_dir)
    cached = (
        manifest.get("version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
        and manifest.get("orientation_fingerprint") == orientation_fingerprint
        and video_path.exists()
        and audio_path.exists()
        and peaks_path.exists()
    )
    try:
        if cached:
            status_payload = _write_asset_status(
                asset_dir,
                status="ready",
                stage="cached",
                progress=1.0,
                detail="Preview assets are ready from cache",
                source_fingerprint=source_fingerprint,
            )
        else:
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="proxy_video",
                progress=0.08,
                detail="Generating browser preview video",
                source_fingerprint=source_fingerprint,
            )
            _generate_proxy_video(source_path, video_path, orientation_decision=normalized_orientation)
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="proxy_webm",
                progress=0.18,
                detail="Generating optional browser fallback video",
                source_fingerprint=source_fingerprint,
            )
            webm_ready = _generate_proxy_webm_best_effort(source_path, webm_path, orientation_decision=normalized_orientation)
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="proxy_audio",
                progress=0.28,
                detail="Generating waveform proxy audio",
                source_fingerprint=source_fingerprint,
            )
            _generate_proxy_audio(source_path, audio_path)
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="loudness_analysis",
                progress=0.55,
                detail="Measuring preview loudness and waveform peaks",
                source_fingerprint=source_fingerprint,
            )
            peaks_payload = _generate_waveform_peaks(audio_path, duration_sec=duration_sec)
            peaks_path.write_text(json.dumps(peaks_payload, ensure_ascii=False), encoding="utf-8")
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="thumbnails",
                progress=0.78,
                detail="Extracting timeline thumbnails",
                source_fingerprint=source_fingerprint,
            )
            thumbnails = _generate_preview_thumbnails(
                source_path,
                asset_dir=asset_dir,
                duration_sec=duration_sec,
                orientation_decision=normalized_orientation,
            )
            manifest = {
                "version": MANUAL_EDITOR_PREVIEW_ASSET_VERSION,
                "source_fingerprint": source_fingerprint,
                "orientation_fingerprint": orientation_fingerprint,
                "orientation_decision": normalized_orientation,
                "video_filename": video_path.name,
                "webm_filename": webm_path.name if webm_ready else "",
                "audio_filename": audio_path.name,
                "peaks_filename": peaks_path.name,
                "thumbnail_items": [{"filename": path.name, "time_sec": time_sec} for path, time_sec in thumbnails],
                "thumbnail_filenames": [path.name for path, _time_sec in thumbnails],
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            status_payload = _write_asset_status(
                asset_dir,
                status="ready",
                stage="ready",
                progress=1.0,
                detail="Preview assets are ready",
                source_fingerprint=source_fingerprint,
            )
    except Exception as exc:
        status_payload = _write_asset_status(
            asset_dir,
            status="failed",
            stage="failed",
            progress=float(status_payload.get("progress") or 0.0),
            detail="Preview asset generation failed",
            error=_short_error(exc),
            source_fingerprint=source_fingerprint,
        )
        raise

    peaks_payload = _read_json(peaks_path)
    thumbnail_items = _manifest_thumbnail_items(manifest, asset_dir)
    return {
        "ready": True,
        "video_ready": True,
        "video_fallback_ready": webm_path.exists(),
        "audio_ready": True,
        "video_path": str(video_path),
        "video_fallback_path": str(webm_path),
        "audio_path": str(audio_path),
        "duration_sec": round(float(peaks_payload.get("duration_sec") or duration_sec or 0.0), 3),
        "sample_rate": int(peaks_payload.get("sample_rate") or 16000),
        "peaks": list(peaks_payload.get("peaks") or []),
        "peak_count": len(list(peaks_payload.get("peaks") or [])),
        "silence_intervals": list(peaks_payload.get("silence_intervals") or []),
        "audio_peak": float(peaks_payload.get("audio_peak") or 0.0),
        "audio_rms": float(peaks_payload.get("audio_rms") or 0.0),
        "audio_lufs": float(peaks_payload.get("audio_lufs") or 0.0),
        "audio_true_peak_db": float(peaks_payload.get("audio_true_peak_db") or 0.0),
        "target_lufs": PREVIEW_AUDIO_TARGET_LUFS,
        "auto_volume_gain": float(peaks_payload.get("auto_volume_gain") or 1.0),
        "thumbnail_paths": [str(item["path"]) for item in thumbnail_items],
        "thumbnail_items": [
            {"path": str(item["path"]), "time_sec": float(item["time_sec"])}
            for item in thumbnail_items
        ],
        "orientation_decision": normalized_orientation,
        "cached": bool(cached),
        **status_payload,
    }


def load_manual_editor_preview_assets(
    *,
    job_id: uuid.UUID | str,
    source_path: Path,
    duration_sec: float,
    asset_dir: Path | str | None = None,
) -> dict[str, Any]:
    asset_dir = _resolve_manual_editor_asset_dir(job_id, asset_dir=asset_dir)
    audio_path = asset_dir / "proxy.wav"
    video_path = asset_dir / "proxy.mp4"
    webm_path = asset_dir / "proxy.webm"
    peaks_path = asset_dir / "peaks.json"
    manifest_path = manual_editor_asset_manifest_path(job_id, asset_dir=asset_dir)
    manifest = _read_json(manifest_path)
    status_payload = _read_asset_status(asset_dir)
    try:
        source_fingerprint = _source_fingerprint(source_path)
    except OSError:
        source_fingerprint = ""
    ready = (
        bool(source_fingerprint)
        and manifest.get("version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
        and video_path.exists()
        and audio_path.exists()
        and peaks_path.exists()
    )
    manifest_matches_source = (
        bool(source_fingerprint)
        and manifest.get("version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
    )
    status_matches_source = (
        bool(source_fingerprint)
        and status_payload.get("asset_version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and status_payload.get("source_fingerprint") == source_fingerprint
    )
    status_video_ready = _status_indicates_completed_proxy(status_payload, stages=_VIDEO_PROXY_READY_STAGES)
    status_webm_ready = _status_indicates_completed_proxy(status_payload, stages=_WEBM_PROXY_READY_STAGES)
    video_ready = bool(video_path.exists() and (manifest_matches_source or (status_matches_source and status_video_ready)))
    video_fallback_ready = bool(webm_path.exists() and (manifest_matches_source or (status_matches_source and status_webm_ready)))
    audio_ready = bool(audio_path.exists() and peaks_path.exists() and (manifest_matches_source or status_matches_source))
    if not ready:
        return {
            "ready": False,
            "video_ready": video_ready,
            "video_fallback_ready": video_fallback_ready,
            "audio_ready": audio_ready,
            "video_path": str(video_path),
            "video_fallback_path": str(webm_path),
            "audio_path": str(audio_path),
            "duration_sec": round(float(duration_sec or 0.0), 3),
            "sample_rate": 16000,
            "peaks": [],
            "peak_count": 0,
            "silence_intervals": [],
            "audio_peak": 0.0,
            "audio_rms": 0.0,
            "audio_lufs": 0.0,
            "audio_true_peak_db": 0.0,
            "target_lufs": PREVIEW_AUDIO_TARGET_LUFS,
            "auto_volume_gain": 1.0,
            "thumbnail_paths": [],
            "thumbnail_items": [],
            "cached": False,
            **_fallback_asset_status(status_payload),
        }

    peaks_payload = _read_json(peaks_path)
    thumbnail_items = _manifest_thumbnail_items(manifest, asset_dir)
    return {
        "ready": True,
        "video_ready": True,
        "video_fallback_ready": webm_path.exists(),
        "audio_ready": True,
        "video_path": str(video_path),
        "video_fallback_path": str(webm_path),
        "audio_path": str(audio_path),
        "duration_sec": round(float(peaks_payload.get("duration_sec") or duration_sec or 0.0), 3),
        "sample_rate": int(peaks_payload.get("sample_rate") or 16000),
        "peaks": list(peaks_payload.get("peaks") or []),
        "peak_count": len(list(peaks_payload.get("peaks") or [])),
        "silence_intervals": list(peaks_payload.get("silence_intervals") or []),
        "audio_peak": float(peaks_payload.get("audio_peak") or 0.0),
        "audio_rms": float(peaks_payload.get("audio_rms") or 0.0),
        "audio_lufs": float(peaks_payload.get("audio_lufs") or 0.0),
        "audio_true_peak_db": float(peaks_payload.get("audio_true_peak_db") or 0.0),
        "target_lufs": PREVIEW_AUDIO_TARGET_LUFS,
        "auto_volume_gain": float(peaks_payload.get("auto_volume_gain") or 1.0),
        "thumbnail_paths": [str(item["path"]) for item in thumbnail_items],
        "thumbnail_items": [
            {"path": str(item["path"]), "time_sec": float(item["time_sec"])}
            for item in thumbnail_items
        ],
        "orientation_decision": manifest.get("orientation_decision") if isinstance(manifest.get("orientation_decision"), dict) else {},
        "cached": True,
        **_fallback_asset_status(
            status_payload,
            default_status="ready",
            default_stage="cached",
            default_progress=1.0,
        ),
    }


def _source_fingerprint(source_path: Path) -> str:
    stat = source_path.stat()
    payload = f"{source_path.resolve()}:{stat.st_size}:{_sampled_file_digest(source_path, stat.st_size)}"
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_orientation_decision(decision: dict[str, Any] | Any | None) -> dict[str, Any]:
    if decision is None:
        payload: dict[str, Any] = {}
    elif hasattr(decision, "to_dict") and callable(decision.to_dict):
        payload = dict(decision.to_dict())
    elif isinstance(decision, dict):
        payload = dict(decision)
    else:
        payload = {}

    try:
        raw_rotation = int(float(payload.get("rotation_cw") or payload.get("rotation") or 0))
    except (TypeError, ValueError):
        raw_rotation = 0
    normalized_rotation = raw_rotation % 360
    rotation_cw = min((0, 90, 180, 270), key=lambda value: min(abs(value - normalized_rotation), 360 - abs(value - normalized_rotation)))
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "rotation_cw": int(rotation_cw),
        "source": str(payload.get("source") or "default").strip() or "default",
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "reason": str(payload.get("reason") or "").strip()[:240],
        "metadata_rotation_cw": _safe_int(payload.get("metadata_rotation_cw"), 0) % 360,
    }


def _orientation_fingerprint(orientation_decision: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_normalize_orientation_decision(orientation_decision), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _sampled_file_digest(source_path: Path, size: int) -> str:
    digest = hashlib.sha256()
    if size <= 0:
        return digest.hexdigest()
    sample_size = 1024 * 1024
    offsets = [0]
    if size > sample_size * 2:
        offsets.append(max(0, (size // 2) - (sample_size // 2)))
    if size > sample_size:
        offsets.append(max(0, size - sample_size))
    with source_path.open("rb") as file:
        for offset in dict.fromkeys(offsets):
            file.seek(offset)
            digest.update(offset.to_bytes(8, "little", signed=False))
            digest.update(file.read(sample_size))
    return digest.hexdigest()


def _status_indicates_completed_proxy(status_payload: dict[str, Any], *, stages: set[str]) -> bool:
    if str(status_payload.get("status") or "").strip() == "failed":
        return False
    return str(status_payload.get("stage") or "").strip() in stages


def _generate_proxy_audio(source_path: Path, audio_path: Path) -> None:
    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 900)),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(f"manual editor proxy audio failed: {result.stderr[-1000:]}")


def _temporary_output_path(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.stem}.{uuid.uuid4().hex}.tmp{target_path.suffix}")


def _unlink_best_effort(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _assert_proxy_video_decodable(video_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-xerror",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-frames:v",
        "120",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(f"manual editor proxy video validation failed: {result.stderr[-1000:]}")


def _orientation_video_filter(orientation_decision: dict[str, Any] | None) -> str:
    rotation_cw = int(_normalize_orientation_decision(orientation_decision).get("rotation_cw") or 0)
    filters: list[str] = []
    if rotation_cw == 90:
        filters.append("transpose=1")
    elif rotation_cw == 180:
        filters.extend(["hflip", "vflip"])
    elif rotation_cw == 270:
        filters.append("transpose=2")
    filters.append("sidedata=mode=delete:type=DISPLAYMATRIX")
    return ",".join(filters)


def _manual_editor_proxy_video_filter(orientation_decision: dict[str, Any] | None) -> str:
    return (
        f"{_orientation_video_filter(orientation_decision)},"
        "scale=960:960:force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"
    )


def _manual_editor_thumbnail_filter(orientation_decision: dict[str, Any] | None) -> str:
    return f"{_orientation_video_filter(orientation_decision)},scale=320:-2"


def _generate_proxy_video(
    source_path: Path,
    video_path: Path,
    *,
    orientation_decision: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    temp_path = _temporary_output_path(video_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-noautorotate",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        _manual_editor_proxy_video_filter(orientation_decision),
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.1",
        "-preset",
        "veryfast",
        "-crf",
        "30",
        "-tune",
        "fastdecode",
        "-g",
        "60",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        "-max_muxing_queue_size",
        "1024",
        str(temp_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 1800)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(f"manual editor proxy video failed: {result.stderr[-1000:]}")
        _assert_proxy_video_decodable(temp_path)
        os.replace(temp_path, video_path)
    finally:
        _unlink_best_effort(temp_path)


def _generate_proxy_webm_best_effort(
    source_path: Path,
    webm_path: Path,
    *,
    orientation_decision: dict[str, Any] | None = None,
) -> bool:
    try:
        _generate_proxy_webm(source_path, webm_path, orientation_decision=orientation_decision)
        return webm_path.exists()
    except Exception:
        return False


def _generate_proxy_webm(
    source_path: Path,
    webm_path: Path,
    *,
    orientation_decision: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    temp_path = _temporary_output_path(webm_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-noautorotate",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        _manual_editor_proxy_video_filter(orientation_decision),
        "-c:v",
        "libvpx",
        "-deadline",
        "realtime",
        "-cpu-used",
        "5",
        "-quality",
        "realtime",
        "-b:v",
        "900k",
        "-maxrate",
        "1200k",
        "-bufsize",
        "2400k",
        "-c:a",
        "libopus",
        "-b:a",
        "96k",
        "-max_muxing_queue_size",
        "1024",
        str(temp_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 1800)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(f"manual editor proxy webm failed: {result.stderr[-1000:]}")
        _assert_proxy_video_decodable(temp_path)
        os.replace(temp_path, webm_path)
    finally:
        _unlink_best_effort(temp_path)


def _generate_waveform_peaks(audio_path: Path, *, duration_sec: float, target_points: int | None = None) -> dict[str, Any]:
    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        resolved_duration = frame_count / float(sample_rate or 1)
        point_count = target_points or max(800, min(16000, int(max(resolved_duration, duration_sec or 0.0) * 25)))
        frames_per_peak = max(1, frame_count // point_count)
        peaks: list[float] = []
        peak = 0.0
        square_sum = 0.0
        sample_count = 0
        for _ in range(0, frame_count, frames_per_peak):
            frames = wav.readframes(frames_per_peak)
            if not frames:
                break
            chunk_peak, chunk_square_sum, chunk_sample_count = _audio_stats_from_pcm(
                frames,
                sample_width=sample_width,
                channels=channels,
            )
            peak = max(peak, chunk_peak)
            square_sum += chunk_square_sum
            sample_count += chunk_sample_count
            peaks.append(round(chunk_peak, 4))
    rms = math.sqrt(square_sum / sample_count) if sample_count > 0 else 0.0
    estimated_lufs = _estimated_lufs_from_rms(rms)
    estimated_true_peak_db = _db_from_amplitude(peak)
    return {
        "duration_sec": round(float(resolved_duration or duration_sec or 0.0), 3),
        "sample_rate": int(sample_rate or 16000),
        "peaks": peaks,
        "silence_intervals": _detect_preview_silence_intervals(
            audio_path,
            peaks=peaks,
            duration_sec=float(resolved_duration or duration_sec or 0.0),
        ),
        "audio_peak": round(peak, 4),
        "audio_rms": round(rms, 4),
        "audio_lufs": round(estimated_lufs, 2) if estimated_lufs is not None else 0.0,
        "audio_true_peak_db": round(estimated_true_peak_db, 2) if estimated_true_peak_db is not None else 0.0,
        "target_lufs": PREVIEW_AUDIO_TARGET_LUFS,
        "auto_volume_gain": _recommended_preview_gain(audio_lufs=estimated_lufs, audio_rms=rms),
    }


def _detect_preview_silence_intervals(audio_path: Path, *, peaks: list[float], duration_sec: float) -> list[dict[str, float]]:
    try:
        silences = detect_silence(
            audio_path,
            aggressiveness=2,
            frame_duration_ms=20,
            min_silence_duration_ms=120,
            padding_ms=20,
        )
        intervals: list[dict[str, float]] = []
        for item in silences:
            start = max(0.0, min(max(0.0, duration_sec), item.start))
            end = max(start, min(max(0.0, duration_sec), item.end))
            if end <= start + 0.08:
                continue
            intervals.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "duration_sec": round(end - start, 3),
            })
        return intervals
    except Exception:
        return _silence_intervals_from_peaks(peaks, duration_sec=duration_sec)


def _silence_intervals_from_peaks(peaks: list[float], *, duration_sec: float) -> list[dict[str, float]]:
    if not peaks or duration_sec <= 0.0:
        return []
    sorted_peaks = sorted(max(0.0, min(1.0, float(peak or 0.0))) for peak in peaks)
    noise_floor = sorted_peaks[max(0, min(len(sorted_peaks) - 1, int(len(sorted_peaks) * 0.18)))]
    threshold = max(0.006, min(0.035, noise_floor * 1.8 + 0.004))
    seconds_per_peak = duration_sec / max(1, len(peaks))
    intervals: list[dict[str, float]] = []
    start_index: int | None = None
    for index, peak in enumerate(peaks):
        silent = max(0.0, float(peak or 0.0)) <= threshold
        if silent and start_index is None:
            start_index = index
        elif not silent and start_index is not None:
            _append_peak_silence_interval(intervals, start_index, index, seconds_per_peak, duration_sec)
            start_index = None
    if start_index is not None:
        _append_peak_silence_interval(intervals, start_index, len(peaks), seconds_per_peak, duration_sec)
    return intervals


def _append_peak_silence_interval(
    intervals: list[dict[str, float]],
    start_index: int,
    end_index: int,
    seconds_per_peak: float,
    duration_sec: float,
) -> None:
    start = max(0.0, start_index * seconds_per_peak)
    end = min(duration_sec, end_index * seconds_per_peak)
    if end <= start + 0.12:
        return
    intervals.append({
        "start": round(start, 3),
        "end": round(end, 3),
        "duration_sec": round(end - start, 3),
    })


def _peak_from_pcm(frames: bytes, *, sample_width: int, channels: int) -> float:
    peak, _square_sum, _sample_count = _audio_stats_from_pcm(frames, sample_width=sample_width, channels=channels)
    return peak


def _audio_stats_from_pcm(frames: bytes, *, sample_width: int, channels: int) -> tuple[float, float, int]:
    if sample_width != 2:
        return 0.0, 0.0, 0
    peak = 0
    square_sum = 0.0
    sample_count = 0
    step = max(2, sample_width * max(1, channels))
    for offset in range(0, len(frames) - 1, step):
        sample = int.from_bytes(frames[offset : offset + 2], byteorder="little", signed=True)
        peak = max(peak, abs(sample))
        normalized = sample / 32768.0
        square_sum += normalized * normalized
        sample_count += 1
    return min(1.0, peak / 32768.0), square_sum, sample_count


def _recommended_preview_gain(*, audio_lufs: float | None = None, audio_rms: float = 0.0, audio_peak: float | None = None) -> float:
    del audio_peak
    if audio_lufs is not None and math.isfinite(audio_lufs):
        gain = 10 ** ((PREVIEW_AUDIO_TARGET_LUFS - float(audio_lufs)) / 20.0)
        return round(max(PREVIEW_AUDIO_MIN_GAIN, min(PREVIEW_AUDIO_MAX_GAIN, gain)), 3)
    rms = max(0.0, min(1.0, float(audio_rms or 0.0)))
    if rms <= 0.0001:
        return 1.0
    target_rms = 10 ** (PREVIEW_AUDIO_TARGET_LUFS / 20.0)
    gain = target_rms / rms
    return round(max(PREVIEW_AUDIO_MIN_GAIN, min(PREVIEW_AUDIO_MAX_GAIN, gain)), 3)


def _estimated_lufs_from_rms(audio_rms: float) -> float | None:
    rms = max(0.0, min(1.0, float(audio_rms or 0.0)))
    if rms <= 0.0001:
        return None
    return _db_from_amplitude(rms)


def _db_from_amplitude(amplitude: float) -> float | None:
    value = max(0.0, min(1.0, float(amplitude or 0.0)))
    if value <= 0.0001:
        return None
    return 20.0 * math.log10(value)


def _generate_preview_thumbnails(
    source_path: Path,
    *,
    asset_dir: Path,
    duration_sec: float,
    orientation_decision: dict[str, Any] | None = None,
) -> list[tuple[Path, float]]:
    if duration_sec <= 0:
        return []
    settings = get_settings()
    timestamps = _thumbnail_timestamps(duration_sec)
    paths: list[tuple[Path, float]] = []
    for index, timestamp in enumerate(timestamps):
        target = asset_dir / f"thumb_{index:03d}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-noautorotate",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            _manual_editor_thumbnail_filter(orientation_decision),
            "-q:v",
            "4",
            str(target),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 180)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and target.exists():
            paths.append((target, round(float(timestamp), 3)))
    return paths


def _thumbnail_timestamps(duration_sec: float, *, target_count: int | None = None) -> list[float]:
    duration = max(0.0, float(duration_sec or 0.0))
    if duration <= 0.0:
        return []
    count = target_count or max(5, min(18, int(duration / 30.0) + 1))
    if count <= 1:
        return [max(0.0, min(duration - 0.1, duration * 0.5))]
    return [
        max(0.0, min(duration - 0.1, duration * ((index + 0.5) / count)))
        for index in range(count)
    ]


def _manifest_thumbnail_items(manifest: dict[str, Any], asset_dir: Path) -> list[dict[str, Any]]:
    raw_items = list(manifest.get("thumbnail_items") or [])
    if not raw_items:
        raw_items = [
            {"filename": str(name), "time_sec": 0.0}
            for name in list(manifest.get("thumbnail_filenames") or [])
        ]
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        filename = Path(str(raw_item.get("filename") or "")).name
        if not filename:
            continue
        path = asset_dir / filename
        if not path.exists():
            continue
        items.append({"path": path, "time_sec": round(float(raw_item.get("time_sec") or 0.0), 3)})
    return items


def _write_asset_status(
    asset_dir: Path,
    *,
    status: str,
    stage: str,
    progress: float,
    detail: str | None = None,
    error: str | None = None,
    source_fingerprint: str | None = None,
) -> dict[str, Any]:
    asset_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "asset_version": MANUAL_EDITOR_PREVIEW_ASSET_VERSION,
        "status": status,
        "stage": stage,
        "progress": max(0.0, min(1.0, float(progress))),
        "detail": detail,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if source_fingerprint:
        payload["source_fingerprint"] = source_fingerprint
    status_path = asset_dir / MANUAL_EDITOR_PREVIEW_STATUS_FILENAME
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _read_asset_status(asset_dir: Path) -> dict[str, Any]:
    return _fallback_asset_status(_read_json(asset_dir / MANUAL_EDITOR_PREVIEW_STATUS_FILENAME))


def _fallback_asset_status(
    payload: dict[str, Any],
    *,
    default_status: str = "missing",
    default_stage: str = "not_started",
    default_progress: float = 0.0,
) -> dict[str, Any]:
    status = str(payload.get("status") or default_status)
    stage = str(payload.get("stage") or default_stage)
    try:
        progress = float(payload.get("progress", default_progress))
    except (TypeError, ValueError):
        progress = default_progress
    return {
        "asset_version": _safe_int(payload.get("asset_version"), MANUAL_EDITOR_PREVIEW_ASSET_VERSION),
        "status": status,
        "stage": stage,
        "progress": max(0.0, min(1.0, progress)),
        "detail": str(payload.get("detail") or "") or None,
        "error": str(payload.get("error") or "") or None,
        "updated_at": str(payload.get("updated_at") or "") or None,
        "source_fingerprint": str(payload.get("source_fingerprint") or "") or None,
    }


def _short_error(exc: Exception) -> str:
    message = str(exc).strip().replace("\r", " ").replace("\n", " ")
    if not message:
        message = exc.__class__.__name__
    return message[-1000:]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return {}
    return {}
