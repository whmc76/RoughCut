from __future__ import annotations

import asyncio
import gc
import importlib
import logging
import re
import subprocess
import threading
import unicodedata
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    payload_to_dict,
)

logger = logging.getLogger(__name__)

_FUNASR_MODEL_ALIASES = {
    "sensevoice-small": "iic/SenseVoiceSmall",
}


class FunASRProvider(TranscriptionProvider):
    """Chinese-first local ASR via FunASR/SenseVoice."""

    def __init__(self, model_name: str = "sensevoice-small") -> None:
        self._model_name = model_name
        self._resolved_model = _FUNASR_MODEL_ALIASES.get(model_name, model_name)
        self._model = None
        self._model_lock = threading.RLock()
        self._idle_timer: threading.Timer | None = None

    def _load_model(self):
        with self._model_lock:
            self._cancel_idle_unload_locked()
            if self._model is None:
                try:
                    from funasr import AutoModel
                except ImportError as exc:
                    raise RuntimeError(
                        "FunASR is not installed. Run: uv sync --extra local-asr"
                    ) from exc

                logger.info("Loading FunASR model=%s", self._resolved_model)
                self._model = AutoModel(
                    model=self._resolved_model,
                    vad_model="fsmn-vad",
                    trust_remote_code=True,
                    disable_update=True,
                )
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
        try:
            model = self._load_model()
            kwargs = self._build_generate_kwargs(lang_code=lang_code, prompt=prompt)
            context = prompt or None
            hotword = kwargs.get("hotword")
            raw_result = model.generate(input=str(audio_path), **kwargs)

            segments: list[TranscriptSegment] = []
            for item in self._extract_segment_payloads(raw_result):
                raw_text = str(item.get("text") or item.get("raw_text") or "").strip()
                text = self._postprocess_text(item)
                if not text:
                    continue
                start, end = self._extract_timing(item, fallback_start=segments[-1].end if segments else 0.0)
                segment = TranscriptSegment(
                    index=len(segments),
                    start=start,
                    end=end,
                    text=text,
                    provider="funasr",
                    model=self._resolved_model,
                    raw_payload=payload_to_dict(item),
                    raw_text=raw_text or text,
                    context=context,
                    hotword=hotword,
                    confidence=item.get("confidence"),
                    logprob=item.get("logprob"),
                    alignment=item.get("alignment"),
                )
                segments.append(segment)

            duration = self._probe_audio_duration(audio_path, fallback=segments[-1].end if segments else 0.0)
            raw_segments = list(segments)
            segments = self._repair_segments(segments, duration=duration)

            for segment in segments:
                if progress_callback is not None:
                    progress_callback(
                        {
                            "segment_count": len(segments),
                            "segment_end": segment.end,
                            "total_duration": duration,
                            "progress": 0.0,
                            "text": segment.text,
                        }
                    )

            if progress_callback is not None and segments:
                progress_callback(
                    {
                        "segment_count": len(segments),
                        "segment_end": duration,
                        "total_duration": duration,
                        "progress": 1.0,
                        "text": segments[-1].text,
                    }
                )
            return TranscriptResult(
                segments=segments,
                language=lang_code,
                duration=duration,
                provider="funasr",
                model=self._resolved_model,
                raw_payload=payload_to_dict(raw_result),
                raw_segments=raw_segments,
                context=context,
                hotword=hotword,
            )
        finally:
            self._schedule_idle_unload()

    def _schedule_idle_unload(self) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "funasr_auto_unload_enabled", True)):
            return
        delay = max(15, int(getattr(settings, "funasr_idle_unload_sec", 600) or 600))
        with self._model_lock:
            self._cancel_idle_unload_locked()
            timer = threading.Timer(delay, self._release_model_if_idle)
            timer.daemon = True
            timer.name = "roughcut-funasr-idle-unload"
            self._idle_timer = timer
            timer.start()

    def _cancel_idle_unload_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _release_model_if_idle(self) -> None:
        with self._model_lock:
            self._idle_timer = None
            self._release_model_locked()

    def _release_model_locked(self) -> None:
        if self._model is None:
            return
        logger.info("Releasing FunASR model=%s after idle timeout", self._resolved_model)
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if hasattr(torch.cuda, "ipc_collect"):
                    torch.cuda.ipc_collect()
        except Exception:
            pass

    def _build_generate_kwargs(self, *, lang_code: str, prompt: str | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "language": "auto" if lang_code == "auto" else lang_code,
            "use_itn": False,
            "batch_size_s": 30,
            "merge_vad": True,
            "merge_length_s": 15,
        }
        hotwords = self._extract_hotwords(prompt)
        if hotwords:
            kwargs["hotword"] = " ".join(hotwords)
        return kwargs

    @staticmethod
    def _extract_segment_payloads(raw_result: Any) -> list[dict[str, Any]]:
        items = raw_result if isinstance(raw_result, list) else [raw_result]
        payloads: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sentence_info = item.get("sentence_info")
            if isinstance(sentence_info, list) and sentence_info:
                payloads.extend(sentence for sentence in sentence_info if isinstance(sentence, dict))
                continue
            payloads.append(item)
        return payloads

    @staticmethod
    def _postprocess_text(payload: dict[str, Any]) -> str:
        text = str(payload.get("text") or payload.get("raw_text") or "").strip()
        if not text:
            return ""
        try:
            module = importlib.import_module("funasr.utils.postprocess_utils")
            rich_transcription_postprocess = getattr(module, "rich_transcription_postprocess")
        except Exception:
            return FunASRProvider._normalize_text(text)
        try:
            normalized = str(rich_transcription_postprocess(text) or "").strip()
        except Exception:
            normalized = text
        return FunASRProvider._normalize_text(normalized)

    @classmethod
    def _extract_timing(cls, payload: dict[str, Any], *, fallback_start: float) -> tuple[float, float]:
        if "start" in payload or "end" in payload:
            start = cls._normalize_time_value(payload.get("start"), fallback=fallback_start)
            end = cls._normalize_time_value(payload.get("end"), fallback=start)
            return start, max(start, end)

        timestamps = payload.get("timestamp")
        if isinstance(timestamps, list) and timestamps:
            start = None
            end = None
            for item in timestamps:
                values = cls._flatten_numeric_values(item)
                if len(values) >= 2:
                    start = values[0] if start is None else min(start, values[0])
                    end = values[-1] if end is None else max(end, values[-1])
            if start is not None and end is not None:
                return cls._normalize_time_value(start, fallback=fallback_start), cls._normalize_time_value(end, fallback=fallback_start)

        return fallback_start, fallback_start

    @staticmethod
    def _flatten_numeric_values(value: Any) -> list[float]:
        if isinstance(value, (int, float)):
            return [float(value)]
        if isinstance(value, (list, tuple)):
            flattened: list[float] = []
            for item in value:
                flattened.extend(FunASRProvider._flatten_numeric_values(item))
            return flattened
        return []

    @staticmethod
    def _normalize_time_value(value: Any, *, fallback: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback
        if number > 1000:
            return number / 1000.0
        return max(0.0, number)

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
                if len(cleaned) < 2 or cleaned in seen:
                    continue
                seen.add(cleaned)
                hotwords.append(cleaned)
        return hotwords[:32]

    @staticmethod
    def _normalize_text(text: str) -> str:
        compact = re.sub(r"<\|[^>]+\|>", "", text)
        compact = "".join(ch for ch in compact if unicodedata.category(ch) != "So")
        compact = re.sub(r"\s+", " ", compact).strip()
        return compact

    def _repair_segments(self, segments: list[TranscriptSegment], *, duration: float) -> list[TranscriptSegment]:
        if not segments:
            return []

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
        if len(repaired) == 1 and duration > 1.0 and (missing_timing or len(repaired[0].text) >= 28):
            return self._split_long_segment(repaired[0], duration=duration)

        if duration > 0:
            for index, segment in enumerate(repaired):
                if (segment.end - segment.start) > 0.01:
                    continue
                start = duration * index / len(repaired)
                end = duration * (index + 1) / len(repaired)
                segment.start = round(start, 3)
                segment.end = round(max(start, end), 3)
        return repaired

    def _split_long_segment(self, segment: TranscriptSegment, *, duration: float) -> list[TranscriptSegment]:
        chunks = self._split_text_chunks(segment.text)
        if len(chunks) <= 1:
            return [
                TranscriptSegment(
                    index=0,
                    start=0.0,
                    end=round(max(duration, 0.0), 3),
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

    @staticmethod
    def _probe_audio_duration(audio_path: Path, *, fallback: float) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    str(audio_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return fallback
        match = re.search(r'"duration"\s*:\s*"?(?P<duration>\d+(?:\.\d+)?)', result.stdout)
        if not match:
            return fallback
        try:
            return max(0.0, float(match.group("duration")))
        except ValueError:
            return fallback
