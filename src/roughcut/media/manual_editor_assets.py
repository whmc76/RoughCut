from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import wave
from typing import Any
import uuid

from roughcut.config import get_settings

MANUAL_EDITOR_PREVIEW_ARTIFACT_TYPE = "manual_editor_preview_assets"
MANUAL_EDITOR_PREVIEW_ASSET_VERSION = 2


def manual_editor_asset_dir(job_id: uuid.UUID | str) -> Path:
    root = Path(get_settings().job_storage_dir).expanduser()
    return root / str(job_id) / "manual-editor"


def manual_editor_asset_manifest_path(job_id: uuid.UUID | str) -> Path:
    return manual_editor_asset_dir(job_id) / "manifest.json"


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
    cached = (
        manifest.get("version") == MANUAL_EDITOR_PREVIEW_ASSET_VERSION
        and manifest.get("source_fingerprint") == source_fingerprint
        and audio_path.exists()
        and peaks_path.exists()
    )
    if not cached:
        _generate_proxy_audio(source_path, audio_path)
        peaks_payload = _generate_waveform_peaks(audio_path, duration_sec=duration_sec)
        peaks_path.write_text(json.dumps(peaks_payload, ensure_ascii=False), encoding="utf-8")
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

    peaks_payload = _read_json(peaks_path)
    thumbnail_items = _manifest_thumbnail_items(manifest, asset_dir)
    return {
        "audio_path": str(audio_path),
        "duration_sec": round(float(peaks_payload.get("duration_sec") or duration_sec or 0.0), 3),
        "sample_rate": int(peaks_payload.get("sample_rate") or 16000),
        "peaks": list(peaks_payload.get("peaks") or []),
        "peak_count": len(list(peaks_payload.get("peaks") or [])),
        "thumbnail_paths": [str(item["path"]) for item in thumbnail_items],
        "thumbnail_items": [
            {"path": str(item["path"]), "time_sec": float(item["time_sec"])}
            for item in thumbnail_items
        ],
        "cached": bool(cached),
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
            "thumbnail_paths": [],
            "thumbnail_items": [],
            "cached": False,
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
        "thumbnail_paths": [str(item["path"]) for item in thumbnail_items],
        "thumbnail_items": [
            {"path": str(item["path"]), "time_sec": float(item["time_sec"])}
            for item in thumbnail_items
        ],
        "cached": True,
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
        for _ in range(0, frame_count, frames_per_peak):
            frames = wav.readframes(frames_per_peak)
            if not frames:
                break
            peaks.append(round(_peak_from_pcm(frames, sample_width=sample_width, channels=channels), 4))
    return {
        "duration_sec": round(float(resolved_duration or duration_sec or 0.0), 3),
        "sample_rate": int(sample_rate or 16000),
        "peaks": peaks,
    }


def _peak_from_pcm(frames: bytes, *, sample_width: int, channels: int) -> float:
    if sample_width != 2:
        return 0.0
    peak = 0
    step = max(2, sample_width * max(1, channels))
    for offset in range(0, len(frames) - 1, step):
        sample = int.from_bytes(frames[offset : offset + 2], byteorder="little", signed=True)
        peak = max(peak, abs(sample))
    return min(1.0, peak / 32768.0)


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
    count = target_count or max(5, min(48, int(duration / 12.0) + 1))
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return {}
    return {}
