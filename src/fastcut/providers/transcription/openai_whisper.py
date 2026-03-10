from __future__ import annotations

from pathlib import Path

import openai

from fastcut.config import get_settings
from fastcut.providers.transcription.base import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    WordTiming,
)


class OpenAIWhisperProvider(TranscriptionProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.transcription_model

    async def transcribe(self, audio_path: Path, *, language: str = "zh-CN") -> TranscriptResult:
        lang_code = language.split("-")[0]  # "zh-CN" → "zh"

        with audio_path.open("rb") as f:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=f,
                language=lang_code,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

        segments: list[TranscriptSegment] = []
        raw_segments = getattr(response, "segments", []) or []

        for idx, seg in enumerate(raw_segments):
            words: list[WordTiming] = []
            for w in getattr(seg, "words", []) or []:
                words.append(WordTiming(word=w.word, start=w.start, end=w.end))

            segments.append(
                TranscriptSegment(
                    index=idx,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                    words=words,
                )
            )

        duration = segments[-1].end if segments else 0.0
        return TranscriptResult(segments=segments, language=language, duration=duration)
