from __future__ import annotations

from pathlib import Path

import openai

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    WordTiming,
)


class OpenAIWhisperProvider(TranscriptionProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(
            api_key=resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
            base_url=settings.openai_base_url.rstrip("/"),
        )
        self._model = settings.transcription_model

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        del progress_callback
        lang_code = language.split("-")[0]  # "zh-CN" → "zh"

        with audio_path.open("rb") as f:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=f,
                language=lang_code,
                prompt=prompt or None,
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
