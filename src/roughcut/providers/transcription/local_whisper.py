from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    WordTiming,
)

logger = logging.getLogger(__name__)


class LocalWhisperProvider(TranscriptionProvider):
    """Uses faster-whisper or whisper.cpp via subprocess/local Python package."""

    def __init__(self, model_size: str = "large-v3") -> None:
        self._model_size = model_size
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                import ctranslate2
                from faster_whisper import WhisperModel

                cuda_devices = ctranslate2.get_cuda_device_count()
                if cuda_devices > 0:
                    device = "cuda"
                    compute_type = "float16"
                else:
                    device = "cpu"
                    compute_type = "int8"
                logger.info(
                    "Loading faster-whisper model=%s on device=%s compute_type=%s",
                    self._model_size,
                    device,
                    compute_type,
                )
                self._model = WhisperModel(self._model_size, device=device, compute_type=compute_type)
            except ImportError as e:
                raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper") from e
        return self._model

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        lang_code = language.split("-")[0]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path, lang_code, progress_callback)

    def _transcribe_sync(
        self,
        audio_path: Path,
        lang_code: str,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        model = self._load_model()
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=lang_code,
            word_timestamps=True,
        )
        total_duration = float(getattr(info, "duration", 0.0) or 0.0)

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(raw_segments):
            words = [WordTiming(word=w.word, start=w.start, end=w.end) for w in (seg.words or [])]
            current = TranscriptSegment(
                index=idx,
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            )
            segments.append(current)
            if progress_callback is not None:
                progress = (current.end / total_duration) if total_duration > 0 else 0.0
                progress_callback(
                    {
                        "segment_count": len(segments),
                        "segment_end": current.end,
                        "total_duration": total_duration,
                        "progress": max(0.0, min(1.0, progress)),
                        "text": current.text,
                    }
                )

        duration = segments[-1].end if segments else 0.0
        return TranscriptResult(segments=segments, language=lang_code, duration=duration)
