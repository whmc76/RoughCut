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
    WordTiming,
    payload_to_dict,
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
        context = prompt or None
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
            words = self._parse_words(item, context=context)
            segment = TranscriptSegment(
                index=len(segments),
                start=start,
                end=end,
                text=text,
                words=words,
                provider="qwen3_asr",
                model=self._model_name,
                raw_payload=dict(item),
                raw_text=text,
                context=context,
                confidence=item.get("confidence"),
                logprob=item.get("logprob"),
                alignment=item.get("alignment"),
            )
            segments.append(segment)

        if duration <= 0.0 and segments:
            duration = segments[-1].end
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
            language=language_value,
            duration=duration,
            provider="qwen3_asr",
            model=self._model_name,
            raw_payload=payload_to_dict(payload),
            raw_segments=raw_segments_copy,
            context=context,
        )

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
            return [
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=round(max(duration, segment.end), 3),
                    text=segment.text,
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

    def _parse_words(self, item: dict, *, context: str | None) -> list[WordTiming]:
        raw_words = (
            item.get("words")
            or item.get("word_timestamps")
            or item.get("timestamps")
            or []
        )
        parsed: list[WordTiming] = []
        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                continue
            word_text = str(raw_word.get("word") or raw_word.get("text") or raw_word.get("token") or "").strip()
            if not word_text:
                continue
            start = max(0.0, float(raw_word.get("start") or raw_word.get("begin") or raw_word.get("start_time") or 0.0))
            end = max(start, float(raw_word.get("end") or raw_word.get("finish") or raw_word.get("end_time") or start))
            parsed.append(
                WordTiming(
                    word=word_text,
                    start=start,
                    end=end,
                    provider="qwen3_asr",
                    model=self._model_name,
                    raw_payload=dict(raw_word),
                    raw_text=str(raw_word.get("raw_text") or word_text),
                    context=context,
                    confidence=raw_word.get("confidence"),
                    logprob=raw_word.get("logprob"),
                    alignment=raw_word.get("alignment"),
                )
            )
        return parsed
