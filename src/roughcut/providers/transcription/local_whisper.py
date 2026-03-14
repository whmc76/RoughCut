from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
import subprocess
import tempfile

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

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model = None
        self._model_device = None

    @staticmethod
    def _is_cuda_runtime_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "cuda" in message

    def _load_model_for_device(self, device: str):
        import ctranslate2
        from faster_whisper import WhisperModel

        compute_type = "float16" if device == "cuda" else "int8"
        logger.info(
            "Loading faster-whisper model=%s on device=%s compute_type=%s",
            self._model_size,
            device,
            compute_type,
        )
        self._model = WhisperModel(self._model_size, device=device, compute_type=compute_type)
        self._model_device = device
        return self._model

    def _load_model(self):
        if self._model is None:
            try:
                import ctranslate2

                cuda_devices = ctranslate2.get_cuda_device_count()
            except ImportError as e:
                raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper") from e
            if cuda_devices > 0:
                try:
                    return self._load_model_for_device("cuda")
                except Exception as exc:
                    if not self._is_cuda_runtime_error(exc):
                        raise
                    logger.warning(
                        "Loading faster-whisper on CUDA failed for model=%s, falling back to CPU: %s",
                        self._model_size,
                        exc,
                    )
                    self._model = None
                    self._model_device = None
            return self._load_model_for_device("cpu")
        return self._model

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        lang_code = language.split("-")[0]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path, lang_code, prompt, progress_callback)

    def _transcribe_sync(
        self,
        audio_path: Path,
        lang_code: str,
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        model = self._load_model()
        try:
            return self._transcribe_with_model(model, audio_path, lang_code, prompt, progress_callback)
        except Exception as exc:
            if self._model_device != "cuda" or not self._is_cuda_runtime_error(exc):
                raise
            logger.warning(
                "CUDA transcription failed for %s with model=%s, retrying on CPU: %s",
                audio_path,
                self._model_size,
                exc,
            )
            self._model = None
            self._model_device = None
            cpu_model = self._load_model_for_device("cpu")
            return self._transcribe_with_model(cpu_model, audio_path, lang_code, prompt, progress_callback)

    def _transcribe_with_model(
        self,
        model,
        audio_path: Path,
        lang_code: str,
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
        *,
        allow_rescue: bool = True,
    ) -> TranscriptResult:
        transcribe_kwargs = self._build_transcribe_kwargs(lang_code=lang_code, prompt=prompt)
        raw_segments, info = self._call_model_transcribe(model, audio_path, transcribe_kwargs)
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
        result = TranscriptResult(segments=segments, language=lang_code, duration=duration)
        if allow_rescue and self._should_rescue_transcript(result):
            rescued = self._rescue_low_quality_transcript(
                model,
                audio_path,
                lang_code,
                prompt,
                result,
            )
            if rescued is not None:
                return rescued
        return result

    def _build_transcribe_kwargs(self, *, lang_code: str, prompt: str | None) -> dict:
        kwargs = {
            "language": lang_code,
            "beam_size": 6 if lang_code == "zh" else 5,
            "best_of": 6 if lang_code == "zh" else 5,
            "condition_on_previous_text": False,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 220,
            },
            "hallucination_silence_threshold": 1.0,
            "compression_ratio_threshold": 2.2,
            "log_prob_threshold": -1.0,
            "no_speech_threshold": 0.45,
            "temperature": 0.0,
            "word_timestamps": True,
            "initial_prompt": prompt or None,
        }
        hotwords = self._extract_hotwords(prompt)
        if hotwords:
            kwargs["hotwords"] = ",".join(hotwords)
        return kwargs

    def _call_model_transcribe(self, model, audio_path: Path, kwargs: dict):
        try:
            return model.transcribe(str(audio_path), **kwargs)
        except TypeError as exc:
            if "hotwords" not in str(exc):
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("hotwords", None)
            return model.transcribe(str(audio_path), **fallback_kwargs)

    def _should_rescue_transcript(self, result: TranscriptResult) -> bool:
        if not result.segments:
            return False
        if result.duration < 20:
            return False
        if len(result.segments) <= 4 and result.duration >= 50:
            return True
        return any(self._segment_looks_unstable(segment.text, segment.end - segment.start) for segment in result.segments)

    @staticmethod
    def _segment_looks_unstable(text: str, duration: float) -> bool:
        compact = re.sub(r"\s+", "", str(text or "").strip())
        if not compact:
            return False
        if duration >= 18 and len(compact) >= 28:
            return True
        clauses = [item for item in re.split(r"[，,。.!！？?；;]", compact) if len(item) >= 3]
        if len(clauses) >= 4:
            counts: dict[str, int] = {}
            for clause in clauses:
                counts[clause] = counts.get(clause, 0) + 1
            if max(counts.values()) >= 3:
                return True
        for size in (4, 5, 6):
            repeats = LocalWhisperProvider._max_repeated_ngram(compact, size)
            if repeats >= 3:
                return True
        return False

    @staticmethod
    def _max_repeated_ngram(text: str, size: int) -> int:
        if len(text) < size * 2:
            return 0
        counts: dict[str, int] = {}
        for index in range(0, len(text) - size + 1):
            gram = text[index:index + size]
            counts[gram] = counts.get(gram, 0) + 1
        return max(counts.values(), default=0)

    def _rescue_low_quality_transcript(
        self,
        model,
        audio_path: Path,
        lang_code: str,
        prompt: str | None,
        result: TranscriptResult,
    ) -> TranscriptResult | None:
        rescued_segments: list[TranscriptSegment] = []
        replaced = False
        next_index = 0
        for segment in result.segments:
            duration = segment.end - segment.start
            if not self._segment_looks_unstable(segment.text, duration):
                rescued_segments.append(
                    TranscriptSegment(
                        index=next_index,
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                        words=segment.words,
                        speaker=segment.speaker,
                    )
                )
                next_index += 1
                continue
            chunk_segments = self._transcribe_segment_in_chunks(
                model,
                audio_path,
                lang_code,
                prompt,
                start=segment.start,
                end=segment.end,
                start_index=next_index,
            )
            if chunk_segments:
                rescued_segments.extend(chunk_segments)
                next_index += len(chunk_segments)
                replaced = True
            else:
                rescued_segments.append(
                    TranscriptSegment(
                        index=next_index,
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                        words=segment.words,
                        speaker=segment.speaker,
                    )
                )
                next_index += 1
        if not replaced:
            return None
        duration = rescued_segments[-1].end if rescued_segments else result.duration
        return TranscriptResult(segments=rescued_segments, language=result.language, duration=duration)

    def _transcribe_segment_in_chunks(
        self,
        model,
        audio_path: Path,
        lang_code: str,
        prompt: str | None,
        *,
        start: float,
        end: float,
        start_index: int,
    ) -> list[TranscriptSegment]:
        chunk_ranges = self._build_chunk_ranges(start, end)
        segments: list[TranscriptSegment] = []
        next_index = start_index
        with tempfile.TemporaryDirectory() as tmpdir:
            for chunk_start, chunk_end in chunk_ranges:
                chunk_path = Path(tmpdir) / f"chunk_{chunk_start:.2f}_{chunk_end:.2f}.wav"
                try:
                    self._export_audio_chunk(audio_path, chunk_path, start=chunk_start, end=chunk_end)
                    chunk_result = self._transcribe_with_model(
                        model,
                        chunk_path,
                        lang_code,
                        prompt,
                        None,
                        allow_rescue=False,
                    )
                except Exception as exc:
                    logger.warning("Chunk rescue transcription failed for %s %.2f-%.2f: %s", audio_path, chunk_start, chunk_end, exc)
                    continue
                for seg in chunk_result.segments:
                    adjusted_words = [
                        WordTiming(word=word.word, start=word.start + chunk_start, end=word.end + chunk_start)
                        for word in seg.words
                    ]
                    segments.append(
                        TranscriptSegment(
                            index=next_index,
                            start=seg.start + chunk_start,
                            end=seg.end + chunk_start,
                            text=seg.text,
                            words=adjusted_words,
                            speaker=seg.speaker,
                        )
                    )
                    next_index += 1
        return segments

    @staticmethod
    def _build_chunk_ranges(start: float, end: float) -> list[tuple[float, float]]:
        chunk_size = 8.0
        min_chunk = 2.5
        ranges: list[tuple[float, float]] = []
        cursor = start
        while cursor < end - 0.1:
            chunk_end = min(end, cursor + chunk_size)
            if chunk_end - cursor >= min_chunk:
                ranges.append((cursor, chunk_end))
            cursor = chunk_end
        return ranges

    @staticmethod
    def _export_audio_chunk(audio_path: Path, chunk_path: Path, *, start: float, end: float) -> None:
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
        )

    @staticmethod
    def _extract_hotwords(prompt: str | None) -> list[str]:
        text = str(prompt or "").strip()
        if not text:
            return []
        hotwords: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"热词：([^。]+)", text):
            for token in re.split(r"[,，/]\s*", match.group(1)):
                cleaned = token.strip()
                if not cleaned or cleaned in seen:
                    continue
                if len(cleaned) < 2:
                    continue
                seen.add(cleaned)
                hotwords.append(cleaned)
        return hotwords[:16]
