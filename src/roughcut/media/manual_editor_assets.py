from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import wave
from typing import Any
import uuid

from roughcut.config import get_settings

MANUAL_EDITOR_PREVIEW_ARTIFACT_TYPE = "manual_editor_preview_assets"
MANUAL_EDITOR_PREVIEW_ASSET_VERSION = 5
MANUAL_EDITOR_PREVIEW_STATUS_FILENAME = "status.json"
PREVIEW_AUDIO_TARGET_LUFS = -16.0
PREVIEW_AUDIO_MIN_GAIN = 0.35
PREVIEW_AUDIO_MAX_GAIN = 12.0


def manual_editor_asset_dir(job_id: uuid.UUID | str) -> Path:
    root = Path(get_settings().job_storage_dir).expanduser()
    return root / str(job_id) / "manual-editor"


def manual_editor_asset_manifest_path(job_id: uuid.UUID | str) -> Path:
    return manual_editor_asset_dir(job_id) / "manifest.json"


def manual_editor_asset_status_path(job_id: uuid.UUID | str) -> Path:
    return manual_editor_asset_dir(job_id) / MANUAL_EDITOR_PREVIEW_STATUS_FILENAME


def mark_manual_editor_preview_assets_queued(job_id: uuid.UUID | str) -> dict[str, Any]:
    return _write_asset_status(
        manual_editor_asset_dir(job_id),
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
) -> dict[str, Any]:
    asset_dir = manual_editor_asset_dir(job_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    audio_path = asset_dir / "proxy.wav"
    peaks_path = asset_dir / "peaks.json"
    manifest_path = manual_editor_asset_manifest_path(job_id)
    source_fingerprint = _source_fingerprint(source_path)

    manifest = _read_json(manifest_path)
    status_payload = _read_asset_status(asset_dir)
    cached = (
        manifest.get("version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
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
            )
        else:
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="proxy_audio",
                progress=0.1,
                detail="Generating waveform proxy audio",
            )
            _generate_proxy_audio(source_path, audio_path)
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="loudness_analysis",
                progress=0.45,
                detail="Measuring preview loudness and waveform peaks",
            )
            peaks_payload = _generate_waveform_peaks(audio_path, duration_sec=duration_sec)
            peaks_path.write_text(json.dumps(peaks_payload, ensure_ascii=False), encoding="utf-8")
            status_payload = _write_asset_status(
                asset_dir,
                status="warming",
                stage="thumbnails",
                progress=0.7,
                detail="Extracting timeline thumbnails",
            )
            thumbnails = _generate_preview_thumbnails(
                source_path,
                asset_dir=asset_dir,
                duration_sec=duration_sec,
            )
            manifest = {
                "version": MANUAL_EDITOR_PREVIEW_ASSET_VERSION,
                "source_fingerprint": source_fingerprint,
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
            )
    except Exception as exc:
        status_payload = _write_asset_status(
            asset_dir,
            status="failed",
            stage="failed",
            progress=float(status_payload.get("progress") or 0.0),
            detail="Preview asset generation failed",
            error=_short_error(exc),
        )
        raise

    peaks_payload = _read_json(peaks_path)
    thumbnail_items = _manifest_thumbnail_items(manifest, asset_dir)
    return {
        "ready": True,
        "audio_path": str(audio_path),
        "duration_sec": round(float(peaks_payload.get("duration_sec") or duration_sec or 0.0), 3),
        "sample_rate": int(peaks_payload.get("sample_rate") or 16000),
        "peaks": list(peaks_payload.get("peaks") or []),
        "peak_count": len(list(peaks_payload.get("peaks") or [])),
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
        "cached": bool(cached),
        **status_payload,
    }


def load_manual_editor_preview_assets(
    *,
    job_id: uuid.UUID | str,
    source_path: Path,
    duration_sec: float,
) -> dict[str, Any]:
    asset_dir = manual_editor_asset_dir(job_id)
    audio_path = asset_dir / "proxy.wav"
    peaks_path = asset_dir / "peaks.json"
    manifest_path = manual_editor_asset_manifest_path(job_id)
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
        and audio_path.exists()
        and peaks_path.exists()
    )
    if not ready:
        return {
            "ready": False,
            "audio_path": str(audio_path),
            "duration_sec": round(float(duration_sec or 0.0), 3),
            "sample_rate": 16000,
            "peaks": [],
            "peak_count": 0,
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
        "audio_path": str(audio_path),
        "duration_sec": round(float(peaks_payload.get("duration_sec") or duration_sec or 0.0), 3),
        "sample_rate": int(peaks_payload.get("sample_rate") or 16000),
        "peaks": list(peaks_payload.get("peaks") or []),
        "peak_count": len(list(peaks_payload.get("peaks") or [])),
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
    payload = f"{source_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


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
        "audio_peak": round(peak, 4),
        "audio_rms": round(rms, 4),
        "audio_lufs": round(estimated_lufs, 2) if estimated_lufs is not None else 0.0,
        "audio_true_peak_db": round(estimated_true_peak_db, 2) if estimated_true_peak_db is not None else 0.0,
        "target_lufs": PREVIEW_AUDIO_TARGET_LUFS,
        "auto_volume_gain": _recommended_preview_gain(audio_lufs=estimated_lufs, audio_rms=rms),
    }


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


def _generate_preview_thumbnails(source_path: Path, *, asset_dir: Path, duration_sec: float) -> list[tuple[Path, float]]:
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
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-2",
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
