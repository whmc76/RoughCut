from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    payload_to_dict,
)


class LocalHTTPASRProvider(TranscriptionProvider):
    def __init__(self, *, model_name: str = "local-asr-current") -> None:
        settings = get_settings()
        self._base_url = settings.local_asr_api_base_url.rstrip("/")
        self._transcribe_path = self._normalize_path(settings.local_asr_transcribe_path or "/transcribe")
        configured_model = str(settings.local_asr_model_name or "").strip()
        self._model_name = configured_model or model_name
        self._hotwords_field = str(settings.local_asr_hotwords_field or "hotwords").strip() or "hotwords"

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        timeout = httpx.Timeout(1800.0, connect=30.0)
        settings = get_settings()
        context = str(prompt or "").strip() or None
        with audio_path.open("rb") as audio_file:
            files = {
                "file": (
                    audio_path.name,
                    audio_file,
                    "application/octet-stream",
                )
            }
            data = {
                self._hotwords_field: context or "",
                "max_new_tokens": str(int(getattr(settings, "local_asr_max_new_tokens", 4096) or 4096)),
            }
            async with hold_managed_gpu_services_async(
                required_urls=[self._base_url],
                reason="local_http_asr_transcribe",
            ):
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self._base_url}{self._transcribe_path}", files=files, data=data)
        response.raise_for_status()
        payload = response.json()

        raw_items = self._extract_segment_items(payload)
        duration = self._resolve_duration(payload, audio_path=audio_path, raw_items=raw_items)
        segments = self._build_segments(raw_items, duration=duration, context=context)
        if not segments:
            text = str(payload.get("text") or "").strip()
            if text:
                segments = [
                    TranscriptSegment(
                        index=0,
                        start=0.0,
                        end=round(duration, 3),
                        text=text,
                        provider="local_http_asr",
                        model=self._model_name,
                        raw_payload=payload_to_dict(payload),
                        raw_text=text,
                        context=context,
                    )
                ]

        raw_segments_copy = list(segments)
        segments = self._repair_segments(segments, duration=duration)

        if progress_callback is not None:
            total = duration if duration > 0 else (segments[-1].end if segments else 0.0)
            for segment in segments:
                progress_callback(
                    {
                        "segment_count": len(segments),
                        "segment_end": segment.end,
                        "total_duration": total,
                        "progress": min(1.0, segment.end / total) if total > 0 else 0.0,
                        "text": segment.text,
                    }
                )

        return TranscriptResult(
            segments=segments,
            language=language,
            duration=duration,
            provider="local_http_asr",
            model=self._model_name,
            raw_payload=payload_to_dict(payload),
            raw_segments=raw_segments_copy,
            context=context,
        )

    def _extract_segment_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_segments = payload.get("segments")
        if isinstance(raw_segments, list) and raw_segments:
            return [dict(item) for item in raw_segments if isinstance(item, dict)]

        text = str(payload.get("text") or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, dict)]
        return []

    def _build_segments(
        self,
        raw_items: list[dict[str, Any]],
        *,
        duration: float,
        context: str | None,
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for item in raw_items:
            text = str(item.get("text") or item.get("Content") or item.get("content") or "").strip()
            if not text:
                continue
            start = self._coerce_time(item.get("start_time", item.get("Start", item.get("start"))), default=0.0)
            end = self._coerce_time(item.get("end_time", item.get("End", item.get("end"))), default=start)
            if duration > 0 and end <= start and len(raw_items) == 1:
                end = duration
            speaker_value = item.get("speaker_id", item.get("Speaker", item.get("speaker")))
            speaker = None if speaker_value is None else str(speaker_value)
            segments.append(
                TranscriptSegment(
                    index=len(segments),
                    start=max(0.0, start),
                    end=max(start, end),
                    text=text,
                    speaker=speaker,
                    provider="local_http_asr",
                    model=self._model_name,
                    raw_payload=dict(item),
                    raw_text=text,
                    context=context,
                )
            )
        return segments

    def _repair_segments(self, segments: list[TranscriptSegment], *, duration: float) -> list[TranscriptSegment]:
        repaired = [
            TranscriptSegment(
                index=index,
                start=max(0.0, float(segment.start)),
                end=max(float(segment.start), float(segment.end)),
                text=segment.text.strip(),
                words=list(segment.words),
                speaker=segment.speaker,
                provider=segment.provider,
                model=segment.model,
                raw_payload=dict(segment.raw_payload),
                raw_text=segment.raw_text or segment.text,
                context=segment.context,
                hotword=segment.hotword,
                confidence=segment.confidence,
                logprob=segment.logprob,
                alignment=segment.alignment,
            )
            for index, segment in enumerate(segments)
            if segment.text.strip()
        ]
        if not repaired:
            return []
        missing_timing = all((segment.end - segment.start) <= 0.01 for segment in repaired)
        if len(repaired) == 1 and duration > 1.0 and (missing_timing or self._text_units(repaired[0].text) >= 28):
            return self._split_long_segment(repaired[0], duration=duration)
        return repaired

    def _split_long_segment(self, segment: TranscriptSegment, *, duration: float) -> list[TranscriptSegment]:
        chunks = self._split_text_chunks(segment.text)
        if len(chunks) <= 1:
            segment.end = round(max(duration, segment.end), 3)
            return [segment]
        total_units = sum(max(1, self._text_units(chunk)) for chunk in chunks)
        cursor = 0.0
        split_segments: list[TranscriptSegment] = []
        for index, chunk in enumerate(chunks):
            weight = max(1, self._text_units(chunk))
            chunk_duration = duration * weight / total_units if total_units > 0 else 0.0
            end = duration if index == len(chunks) - 1 else min(duration, cursor + chunk_duration)
            split_segments.append(
                TranscriptSegment(
                    index=index,
                    start=round(cursor, 3),
                    end=round(max(cursor, end), 3),
                    text=chunk,
                    speaker=segment.speaker,
                    provider=segment.provider,
                    model=segment.model,
                    raw_payload=dict(segment.raw_payload),
                    raw_text=segment.raw_text or segment.text,
                    context=segment.context,
                )
            )
            cursor = end
        return split_segments

    @classmethod
    def _split_text_chunks(cls, text: str, *, target_units: int = 22, hard_limit: int = 30) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        pieces: list[str] = []
        current = ""
        last_soft_break = -1
        for char in normalized:
            current += char
            if char in "。！？!?；;，,":
                last_soft_break = len(current)
            units = cls._text_units(current)
            if units < target_units:
                continue
            if char in "。！？!?；;" or units >= hard_limit:
                split_at = last_soft_break if last_soft_break >= max(1, len(current) // 2) else len(current)
                chunk = current[:split_at].strip(" ，,")
                rest = current[split_at:].strip()
                if chunk:
                    pieces.append(chunk)
                current = rest
                last_soft_break = -1
        tail = current.strip(" ，,")
        if tail:
            pieces.append(tail)
        return pieces

    @staticmethod
    def _normalize_path(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "/"
        return text if text.startswith("/") else f"/{text}"

    @staticmethod
    def _text_units(text: str) -> int:
        return len(re.sub(r"\s+", "", text))

    @staticmethod
    def _coerce_time(value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _resolve_duration(self, payload: dict[str, Any], *, audio_path: Path, raw_items: list[dict[str, Any]]) -> float:
        for key in ("duration", "duration_seconds"):
            try:
                duration = float(payload.get(key) or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
        end_times = [
            self._coerce_time(item.get("end_time", item.get("End", item.get("end"))), default=0.0)
            for item in raw_items
        ]
        if end_times and max(end_times) > 0:
            return max(end_times)
        return self._probe_duration(audio_path)

    @staticmethod
    def _probe_duration(path: Path) -> float:
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
