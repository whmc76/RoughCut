from __future__ import annotations

import re
from pathlib import Path

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
)


class QwenASRHTTPProvider(TranscriptionProvider):
    def __init__(self, *, model_name: str = "qwen3-asr-1.7b") -> None:
        settings = get_settings()
        self._base_url = settings.qwen_asr_api_base_url.rstrip("/")
        self._model_name = model_name

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        timeout = httpx.Timeout(1800.0, connect=30.0)
        with audio_path.open("rb") as audio_file:
            files = {
                "file": (
                    audio_path.name,
                    audio_file,
                    "application/octet-stream",
                )
            }
            data = {
                "language": language,
                "prompt": prompt or "",
            }
            async with hold_managed_gpu_services_async(
                required_urls=[self._base_url],
                reason="qwen_asr_transcribe",
            ):
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self._base_url}/transcribe", files=files, data=data)
        response.raise_for_status()
        payload = response.json()

        segments: list[TranscriptSegment] = []
        raw_segments = payload.get("segments") or []
        duration = float(payload.get("duration") or 0.0)
        language_value = str(payload.get("language") or language)

        for index, item in enumerate(raw_segments):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = max(0.0, float(item.get("start") or 0.0))
            end = max(start, float(item.get("end") or start))
            segment = TranscriptSegment(index=len(segments), start=start, end=end, text=text)
            segments.append(segment)

        if duration <= 0.0 and segments:
            duration = segments[-1].end
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
        return TranscriptResult(segments=segments, language=language_value, duration=duration)

    def _repair_segments(self, segments: list[TranscriptSegment], *, duration: float) -> list[TranscriptSegment]:
        repaired = [
            TranscriptSegment(
                index=index,
                start=max(0.0, float(segment.start)),
                end=max(float(segment.start), float(segment.end)),
                text=segment.text.strip(),
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
            return [
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=round(max(duration, segment.end), 3),
                    text=segment.text,
                )
            ]

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
    def _text_units(text: str) -> int:
        return len(re.sub(r"\s+", "", text))
