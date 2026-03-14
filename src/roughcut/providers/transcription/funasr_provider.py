from __future__ import annotations

import asyncio
import importlib
import logging
import re
from pathlib import Path
from typing import Any

from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
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

    def _load_model(self):
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
        model = self._load_model()
        kwargs = self._build_generate_kwargs(lang_code=lang_code, prompt=prompt)
        raw_result = model.generate(input=str(audio_path), **kwargs)

        segments: list[TranscriptSegment] = []
        for index, item in enumerate(self._extract_segment_payloads(raw_result)):
            text = self._postprocess_text(item)
            if not text:
                continue
            start, end = self._extract_timing(item, fallback_start=segments[-1].end if segments else 0.0)
            segment = TranscriptSegment(
                index=len(segments),
                start=start,
                end=end,
                text=text,
            )
            segments.append(segment)
            if progress_callback is not None:
                progress_callback(
                    {
                        "segment_count": len(segments),
                        "segment_end": segment.end,
                        "total_duration": max(segment.end, segments[-1].end if segments else 0.0),
                        "progress": 0.0,
                        "text": segment.text,
                    }
                )

        duration = segments[-1].end if segments else 0.0
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
        return TranscriptResult(segments=segments, language=lang_code, duration=duration)

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
            return text
        try:
            return str(rich_transcription_postprocess(text) or "").strip()
        except Exception:
            return text

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
