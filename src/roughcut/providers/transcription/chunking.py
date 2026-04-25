from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming


@dataclass(frozen=True)
class AudioChunkConfig:
    enabled: bool
    threshold_sec: float
    chunk_size_sec: float
    min_chunk_sec: float
    overlap_sec: float
    request_timeout_sec: float
    request_max_retries: int = 2
    request_retry_backoff_sec: float = 5.0
    export_timeout_sec: float = 180.0

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "enabled": bool(self.enabled),
            "threshold_sec": round(float(self.threshold_sec), 3),
            "chunk_size_sec": round(float(self.chunk_size_sec), 3),
            "min_chunk_sec": round(float(self.min_chunk_sec), 3),
            "overlap_sec": round(float(self.overlap_sec), 3),
            "request_timeout_sec": round(float(self.request_timeout_sec), 3),
            "request_max_retries": int(self.request_max_retries),
            "request_retry_backoff_sec": round(float(self.request_retry_backoff_sec), 3),
            "export_timeout_sec": round(float(self.export_timeout_sec), 3),
        }


@dataclass(frozen=True)
class AudioChunkSpec:
    index: int
    count: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, float(self.end) - float(self.start))


def resolve_audio_chunk_config(settings: object) -> AudioChunkConfig:
    chunk_size_sec = max(15.0, float(getattr(settings, "transcription_chunk_size_sec", 60.0) or 60.0))
    min_chunk_sec = min(
        chunk_size_sec,
        max(5.0, float(getattr(settings, "transcription_chunk_min_sec", 20.0) or 20.0)),
    )
    overlap_sec = min(
        max(0.0, float(getattr(settings, "transcription_chunk_overlap_sec", 1.5) or 0.0)),
        max(0.0, chunk_size_sec - min_chunk_sec),
    )
    request_timeout_sec = max(
        30.0,
        float(getattr(settings, "transcription_chunk_request_timeout_sec", 180.0) or 180.0),
    )
    ffmpeg_timeout_sec = max(30.0, float(getattr(settings, "ffmpeg_timeout_sec", 600.0) or 600.0))
    return AudioChunkConfig(
        enabled=bool(getattr(settings, "transcription_chunking_enabled", True)),
        threshold_sec=max(60.0, float(getattr(settings, "transcription_chunk_threshold_sec", 180.0) or 180.0)),
        chunk_size_sec=chunk_size_sec,
        min_chunk_sec=min_chunk_sec,
        overlap_sec=overlap_sec,
        request_timeout_sec=request_timeout_sec,
        request_max_retries=max(
            0,
            int(getattr(settings, "transcription_chunk_request_max_retries", 2) or 0),
        ),
        request_retry_backoff_sec=max(
            0.5,
            float(getattr(settings, "transcription_chunk_request_retry_backoff_sec", 5.0) or 5.0),
        ),
        export_timeout_sec=max(30.0, min(ffmpeg_timeout_sec, request_timeout_sec)),
    )


def should_chunk_audio(*, duration: float, config: AudioChunkConfig) -> bool:
    return bool(config.enabled and duration >= config.threshold_sec and config.chunk_size_sec > 0)


def build_audio_chunk_specs(duration: float, *, config: AudioChunkConfig) -> list[AudioChunkSpec]:
    if duration <= 0:
        return []
    if not should_chunk_audio(duration=duration, config=config):
        return [AudioChunkSpec(index=0, count=1, start=0.0, end=round(duration, 3))]

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    step = max(config.chunk_size_sec - config.overlap_sec, config.min_chunk_sec)
    while cursor < duration - 0.1:
        chunk_end = min(duration, cursor + config.chunk_size_sec)
        if chunk_end - cursor >= config.min_chunk_sec or not ranges:
            ranges.append((round(cursor, 3), round(chunk_end, 3)))
        if chunk_end >= duration:
            break
        cursor = min(duration, cursor + step)

    if not ranges:
        ranges = [(0.0, round(duration, 3))]
    elif ranges[-1][1] < round(duration, 3):
        last_start, _ = ranges[-1]
        ranges[-1] = (last_start, round(duration, 3))
    count = len(ranges)
    return [
        AudioChunkSpec(index=index, count=count, start=start, end=end)
        for index, (start, end) in enumerate(ranges)
    ]


def export_audio_chunk(
    audio_path: Path,
    chunk_path: Path,
    *,
    start: float,
    end: float,
    timeout_sec: float | None = None,
) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(chunk_path),
        ],
        check=True,
        timeout=None if timeout_sec is None or timeout_sec <= 0 else float(timeout_sec),
    )


def probe_audio_duration(path: Path) -> float:
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
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def merge_chunk_result_segments(
    result: TranscriptResult,
    *,
    chunk: AudioChunkSpec,
    start_index: int,
    emitted_end: float,
) -> tuple[list[TranscriptSegment], float]:
    merged: list[TranscriptSegment] = []
    next_index = start_index
    current_end = max(0.0, float(emitted_end))
    for seg in list(result.segments or []):
        absolute_start = round(float(seg.start) + chunk.start, 3)
        absolute_end = round(float(seg.end) + chunk.start, 3)
        if absolute_end <= current_end + 0.05:
            continue
        adjusted_words: list[WordTiming] = []
        for word in list(seg.words or []):
            word_start = round(float(word.start) + chunk.start, 3)
            word_end = round(float(word.end) + chunk.start, 3)
            if word_end <= current_end + 0.05:
                continue
            adjusted_words.append(
                WordTiming(
                    word=word.word,
                    start=max(current_end, word_start) if word_start < current_end else word_start,
                    end=word_end,
                    provider=word.provider,
                    model=word.model,
                    raw_payload=dict(word.raw_payload),
                    raw_text=word.raw_text,
                    context=word.context,
                    hotword=word.hotword,
                    confidence=word.confidence,
                    logprob=word.logprob,
                    alignment=word.alignment,
                )
            )
        merged_segment = TranscriptSegment(
            index=next_index,
            start=max(current_end, absolute_start) if absolute_start < current_end else absolute_start,
            end=absolute_end,
            text=seg.text,
            words=adjusted_words,
            speaker=seg.speaker,
            provider=seg.provider,
            model=seg.model,
            raw_payload=dict(seg.raw_payload),
            raw_text=seg.raw_text or seg.text,
            context=seg.context,
            hotword=seg.hotword,
            confidence=seg.confidence,
            logprob=seg.logprob,
            alignment=seg.alignment,
        )
        merged.append(merged_segment)
        next_index += 1
        current_end = max(current_end, absolute_end)
    return merged, current_end


def chunk_progress_payload(
    *,
    chunk: AudioChunkSpec,
    covered_until: float,
    total_duration: float,
    segment_count: int,
    text: str,
    phase: str | None = None,
    detail: str | None = None,
    retry_attempt: int | None = None,
    retry_count: int | None = None,
) -> dict[str, Any]:
    payload = {
        "segment_count": segment_count,
        "segment_end": round(covered_until, 3),
        "total_duration": round(total_duration, 3),
        "progress": min(1.0, covered_until / total_duration) if total_duration > 0 else 0.0,
        "text": text,
        "chunk_index": int(chunk.index + 1),
        "chunk_count": int(chunk.count),
        "chunk_start": round(chunk.start, 3),
        "chunk_end": round(chunk.end, 3),
    }
    if phase:
        payload["phase"] = str(phase)
    if detail:
        payload["detail"] = str(detail)
    if retry_attempt is not None:
        payload["retry_attempt"] = int(retry_attempt)
    if retry_count is not None:
        payload["retry_count"] = int(retry_count)
    return payload


def extract_chunking_summary(raw_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}
    chunking = payload.get("chunking")
    if not isinstance(chunking, dict):
        return None
    summary: dict[str, Any] = {}
    for key in (
        "enabled",
        "threshold_sec",
        "chunk_size_sec",
        "min_chunk_sec",
        "overlap_sec",
        "request_timeout_sec",
        "request_max_retries",
        "request_retry_backoff_sec",
        "export_timeout_sec",
        "chunk_count",
        "duration_sec",
    ):
        if key in chunking:
            summary[key] = chunking[key]
    return summary or None
