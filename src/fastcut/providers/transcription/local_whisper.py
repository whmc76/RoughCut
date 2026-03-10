from __future__ import annotations

import asyncio
from pathlib import Path

from fastcut.providers.transcription.base import (
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    WordTiming,
)


class LocalWhisperProvider(TranscriptionProvider):
    """Uses faster-whisper or whisper.cpp via subprocess/local Python package."""

    def __init__(self, model_size: str = "large-v3") -> None:
        self._model_size = model_size
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self._model_size, device="auto", compute_type="int8")
            except ImportError as e:
                raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper") from e
        return self._model

    async def transcribe(self, audio_path: Path, *, language: str = "zh-CN") -> TranscriptResult:
        lang_code = language.split("-")[0]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path, lang_code)

    def _transcribe_sync(self, audio_path: Path, lang_code: str) -> TranscriptResult:
        model = self._load_model()
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=lang_code,
            word_timestamps=True,
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(raw_segments):
            words = [WordTiming(word=w.word, start=w.start, end=w.end) for w in (seg.words or [])]
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
        return TranscriptResult(segments=segments, language=lang_code, duration=duration)
