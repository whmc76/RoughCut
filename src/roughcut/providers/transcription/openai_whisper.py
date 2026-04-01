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
    payload_to_dict,
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
        context = prompt or None

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
                words.append(
                    WordTiming(
                        word=w.word,
                        start=w.start,
                        end=w.end,
                        provider="openai",
                        model=self._model,
                        raw_payload=payload_to_dict(w),
                        raw_text=str(getattr(w, "word", "") or None),
                        context=context,
                        confidence=getattr(w, "confidence", None),
                        logprob=getattr(w, "logprob", None),
                        alignment=getattr(w, "alignment", None),
                    )
                )

            segments.append(
                TranscriptSegment(
                    index=idx,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                    words=words,
                    provider="openai",
                    model=self._model,
                    raw_payload=payload_to_dict(seg),
                    raw_text=seg.text.strip(),
                    context=context,
                    confidence=getattr(seg, "confidence", None),
                    logprob=getattr(seg, "avg_logprob", None),
                    alignment=getattr(seg, "alignment", None),
                )
            )

        duration = segments[-1].end if segments else 0.0
        return TranscriptResult(
            segments=segments,
            language=language,
            duration=duration,
            provider="openai",
            model=self._model,
            raw_payload=payload_to_dict(response),
            raw_segments=list(segments),
            context=context,
        )
