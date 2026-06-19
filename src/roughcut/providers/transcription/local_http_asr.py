from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
import re
from pathlib import Path
import tempfile
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.media.silence import detect_silence
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
    WordTiming,
    payload_to_dict,
)
from roughcut.providers.transcription.chunking import (
    build_audio_chunk_specs,
    chunk_progress_payload,
    export_audio_chunk,
    merge_chunk_result_segments,
    probe_audio_duration,
    resolve_audio_chunk_config,
    should_chunk_audio,
)
from roughcut.review.hotword_learning import extract_prompt_hotwords


class LocalHTTPASRProvider(TranscriptionProvider):
    _MODEL_BASE_URL_ENV_KEYS = {
        "fun-asr-nano-2512": "LOCAL_ASR_FUNASR_NANO_2512_BASE_URL",
        "faster-whisper-large-v3-beam5-nohot": "LOCAL_ASR_FASTER_WHISPER_LARGE_V3_BASE_URL",
    }
    _MODEL_BASE_URL_DEFAULTS = {
        "fun-asr-nano-2512": "http://127.0.0.1:30210",
        "faster-whisper-large-v3-beam5-nohot": "http://127.0.0.1:30200",
    }
    _QWEN3_ASR_MAX_CHUNK_SEC = 75.0
    _QWEN3_ASR_RETRY_CHUNK_SEC = 30.0
    _QWEN3_ASR_RETRY_MIN_CHUNK_SEC = 12.0
    _QWEN3_ASR_MIN_MAX_NEW_TOKENS = 512
    _QWEN3_ASR_MID_MAX_NEW_TOKENS = 768
    _QWEN3_ASR_MAX_MAX_NEW_TOKENS = 1024
    _QWEN3_ASR_TAIL_GAP_MIN_SEC = 6.0
    _QWEN3_ASR_TAIL_GAP_MIN_RATIO = 0.12
    _QWEN3_ASR_VOICED_TAIL_MIN_SEC = 1.2
    _DECODE_LOOP_MIN_TEXT_UNITS = 12
    _DECODE_LOOP_MIN_REPEATS = 4
    _SHORT_DUPLICATE_NOISE_TERMS = frozenset(
        {
            "啊", "呃", "嗯", "哦", "哎", "诶", "呀", "呢", "嘛", "吧", "吗",
            "了", "的", "还", "又", "就", "也", "都", "再", "很", "太",
            "是", "个", "我", "你", "他", "她", "它", "给", "把",
        }
    )
    _SHORT_PREFIX_DUPLICATE_NOISE_TERMS = frozenset({"开", "有", "借", "简"})
    _SHORT_DUPLICATE_NOISE_RE = re.compile(r"([啊呃嗯哦哎诶呀呢嘛吧吗了的还又就也都再很太是个我你他她它给把])\1+")
    _SHORT_PREFIX_DUPLICATE_NOISE_RE = re.compile(r"([开有借简])\1(?=[\u4e00-\u9fff])")
    _LONG_LAUGHTER_DUPLICATE_NOISE_RE = re.compile(r"([哈嘿呵嘻哼])\1{2,}")
    _LONG_CJK_DUPLICATE_NOISE_RE = re.compile(r"([\u4e00-\u9fff])\1{3,}")

    def __init__(self, *, model_name: str | None = None) -> None:
        settings = get_settings()
        self._transcribe_path = self._normalize_path(settings.local_asr_transcribe_path or "/transcribe")
        explicit_model = str(model_name or "").strip()
        configured_model = str(settings.local_asr_model_name or "").strip()
        self._model_name = explicit_model or configured_model or "faster-whisper-large-v3-beam5-nohot"
        self._base_url = self._resolve_base_url_for_model(
            self._model_name,
            default_base_url=str(settings.local_asr_api_base_url or ""),
        ).rstrip("/")
        self._hotwords_field = str(settings.local_asr_hotwords_field or "hotwords").strip() or "hotwords"
        self._hotwords_enabled = bool(getattr(settings, "local_asr_hotwords_enabled", False))
        self._beam_size = max(1, int(getattr(settings, "local_asr_beam_size", 5) or 5))
        self._best_of = max(1, int(getattr(settings, "local_asr_best_of", 5) or 5))
        self._condition_on_previous_text = bool(getattr(settings, "local_asr_condition_on_previous_text", False))
        self._vad_filter = bool(getattr(settings, "local_asr_vad_filter", True))

    @classmethod
    def _resolve_base_url_for_model(cls, model_name: str, *, default_base_url: str) -> str:
        normalized_model = str(model_name or "").strip().lower()
        env_key = cls._MODEL_BASE_URL_ENV_KEYS.get(normalized_model)
        if env_key:
            override = str(os.getenv(env_key) or "").strip()
            if override:
                return override
        return cls._MODEL_BASE_URL_DEFAULTS.get(normalized_model) or default_base_url or "http://127.0.0.1:30230"

    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        settings = get_settings()
        context = self._resolve_hotword_context(prompt)
        chunk_config = self._resolve_effective_chunk_config(resolve_audio_chunk_config(settings))
        probed_duration = probe_audio_duration(audio_path)
        max_new_tokens = self._resolve_max_new_tokens(settings, audio_duration=probed_duration)
        if should_chunk_audio(duration=probed_duration, config=chunk_config):
            return await self._transcribe_long_audio_in_chunks(
                audio_path,
                language=language,
                context=context,
                total_duration=probed_duration,
                max_new_tokens=max_new_tokens,
                chunk_config=chunk_config,
                progress_callback=progress_callback,
            )
        return await self._transcribe_single_audio(
            audio_path,
            language=language,
            context=context,
            max_new_tokens=max_new_tokens,
            progress_callback=progress_callback,
        )

    async def _transcribe_single_audio(
        self,
        audio_path: Path,
        *,
        language: str,
        context: str | None,
        max_new_tokens: int,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> TranscriptResult:
        if progress_callback is not None:
            duration = probe_audio_duration(audio_path)
            progress_callback(
                {
                    "segment_count": 0,
                    "segment_end": 0.0,
                    "total_duration": round(duration, 3),
                    "progress": 0.0,
                    "phase": "request",
                    "detail": "提交整段音频转写请求",
                }
            )
        payload = await self._post_transcribe_request(
            audio_path,
            context=context,
            max_new_tokens=max_new_tokens,
            timeout=httpx.Timeout(1800.0, connect=30.0),
        )
        return self._build_result_from_payload(
            payload,
            audio_path=audio_path,
            language=language,
            context=context,
            progress_callback=progress_callback,
        )

    async def _transcribe_long_audio_in_chunks(
        self,
        audio_path: Path,
        *,
        language: str,
        context: str | None,
        total_duration: float,
        max_new_tokens: int,
        chunk_config,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> TranscriptResult:
        chunk_specs = build_audio_chunk_specs(total_duration, config=chunk_config)
        segments: list[TranscriptSegment] = []
        payloads: list[dict[str, Any]] = []
        next_index = 0
        emitted_end = 0.0
        with tempfile.TemporaryDirectory() as tmpdir:
            for chunk in chunk_specs:
                chunk_result, chunk_payload_group = await self._transcribe_chunk_with_anchor_recovery(
                    audio_path=audio_path,
                    tmpdir=Path(tmpdir),
                    chunk=chunk,
                    context=context,
                    language=language,
                    max_new_tokens=max_new_tokens,
                    chunk_config=chunk_config,
                    covered_until=emitted_end,
                    total_duration=total_duration,
                    segment_count=len(segments),
                    latest_text=segments[-1].text if segments else "",
                    progress_callback=progress_callback,
                )
                payloads.extend(chunk_payload_group)
                merged_segments, emitted_end = merge_chunk_result_segments(
                    chunk_result,
                    chunk=chunk,
                    start_index=next_index,
                    emitted_end=emitted_end,
                )
                segments.extend(merged_segments)
                next_index += len(merged_segments)
                if progress_callback is not None:
                    progress_callback(
                        chunk_progress_payload(
                            chunk=chunk,
                            covered_until=max(emitted_end, chunk.end),
                            total_duration=total_duration,
                            segment_count=len(segments),
                            text=segments[-1].text if segments else "",
                            phase="complete",
                            detail=f"chunk {chunk.index + 1}/{chunk.count} 转写完成",
                        )
                    )

        if self._decode_loop_sanitizer_enabled():
            segments = self._sanitize_decode_loop_segments(
                segments,
                repeated_segment_strategy="drop",
                repeated_segment_min_repeats=2,
            )
        raw_segments = list(segments)
        repair_duration = max((float(segment.end) for segment in segments), default=total_duration)
        repaired_segments = self._repair_segments(segments, duration=repair_duration)
        if self._decode_loop_sanitizer_enabled():
            repaired_segments = self._sanitize_decode_loop_segments(
                repaired_segments,
                repeated_segment_strategy="drop",
                repeated_segment_min_repeats=2,
            )
        return TranscriptResult(
            segments=repaired_segments,
            language=language,
            duration=total_duration,
            provider="local_http_asr",
            model=self._model_name,
            raw_payload={
                "chunking": {
                    **chunk_config.as_dict(),
                    "chunk_count": len(chunk_specs),
                    "duration_sec": round(total_duration, 3),
                },
                "chunks": payloads,
            },
            raw_segments=raw_segments or list(repaired_segments),
            context=context,
            hotword=context,
        )

    async def _transcribe_chunk_with_anchor_recovery(
        self,
        *,
        audio_path: Path,
        tmpdir: Path,
        chunk,
        context: str | None,
        language: str,
        max_new_tokens: int,
        chunk_config,
        covered_until: float,
        total_duration: float,
        segment_count: int,
        latest_text: str,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> tuple[TranscriptResult, list[dict[str, Any]]]:
        chunk_path = tmpdir / f"chunk_{chunk.start:.2f}_{chunk.end:.2f}.wav"
        await self._export_chunk_audio(
            audio_path=audio_path,
            chunk_path=chunk_path,
            chunk=chunk,
            chunk_config=chunk_config,
            covered_until=covered_until,
            total_duration=total_duration,
            segment_count=segment_count,
            latest_text=latest_text,
            progress_callback=progress_callback,
        )
        payloads: list[dict[str, Any]] = []
        chunk_payload = await self._post_chunk_transcribe_request(
            chunk_path=chunk_path,
            chunk=chunk,
            context=context,
            max_new_tokens=max_new_tokens,
            timeout=httpx.Timeout(float(chunk_config.request_timeout_sec), connect=30.0),
            chunk_config=chunk_config,
            covered_until=covered_until,
            total_duration=total_duration,
            segment_count=segment_count,
            latest_text=latest_text,
            progress_callback=progress_callback,
        )
        payloads.append(payload_to_dict(chunk_payload))
        chunk_result = self._build_result_from_payload(
            chunk_payload,
            audio_path=chunk_path,
            language=language,
            context=context,
            progress_callback=None,
        )
        if not self._should_retry_chunk_for_anchor_recovery(
            chunk_result=chunk_result,
            chunk=chunk,
            chunk_path=chunk_path,
        ):
            return chunk_result, payloads

        recovered_result, retry_payloads = await self._retry_chunk_with_smaller_splits(
            audio_path=audio_path,
            tmpdir=tmpdir,
            parent_chunk=chunk,
            context=context,
            language=language,
            parent_chunk_config=chunk_config,
            covered_until=covered_until,
            total_duration=total_duration,
            segment_count=segment_count,
            latest_text=latest_text,
            progress_callback=progress_callback,
        )
        payloads.extend(retry_payloads)
        if self._covered_end_seconds(recovered_result) > self._covered_end_seconds(chunk_result) + 1.0:
            return recovered_result, payloads
        return chunk_result, payloads

    async def _retry_chunk_with_smaller_splits(
        self,
        *,
        audio_path: Path,
        tmpdir: Path,
        parent_chunk,
        context: str | None,
        language: str,
        parent_chunk_config,
        covered_until: float,
        total_duration: float,
        segment_count: int,
        latest_text: str,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> tuple[TranscriptResult, list[dict[str, Any]]]:
        retry_config = replace(
            parent_chunk_config,
            enabled=True,
            threshold_sec=0.0,
            chunk_size_sec=min(float(parent_chunk.duration), self._QWEN3_ASR_RETRY_CHUNK_SEC),
            min_chunk_sec=min(
                float(parent_chunk.duration),
                min(float(parent_chunk_config.min_chunk_sec), self._QWEN3_ASR_RETRY_MIN_CHUNK_SEC),
            ),
            overlap_sec=0.0,
        )
        retry_specs = build_audio_chunk_specs(float(parent_chunk.duration), config=retry_config)
        if len(retry_specs) <= 1:
            return TranscriptResult(
                segments=[],
                language=language,
                duration=float(parent_chunk.duration),
                provider="local_http_asr",
                model=self._model_name,
                raw_payload={"anchor_recovery": "skipped"},
            ), []

        if progress_callback is not None:
            progress_callback(
                chunk_progress_payload(
                    chunk=parent_chunk,
                    covered_until=covered_until,
                    total_duration=total_duration,
                    segment_count=segment_count,
                    text=latest_text,
                    phase="anchor_recovery",
                    detail=(
                        f"chunk {parent_chunk.index + 1}/{parent_chunk.count} 覆盖不足，"
                        f"拆成 {len(retry_specs)} 个更短片段重跑"
                    ),
                )
            )

        payloads: list[dict[str, Any]] = []
        recovered_segments: list[TranscriptSegment] = []
        local_emitted_end = 0.0
        local_next_index = 0
        for retry_chunk in retry_specs:
            absolute_chunk = replace(
                retry_chunk,
                start=round(float(parent_chunk.start) + float(retry_chunk.start), 3),
                end=round(float(parent_chunk.start) + float(retry_chunk.end), 3),
            )
            retry_chunk_path = tmpdir / (
                f"chunk_{parent_chunk.start:.2f}_{parent_chunk.end:.2f}_retry_{retry_chunk.index + 1}.wav"
            )
            await self._export_chunk_audio(
                audio_path=audio_path,
                chunk_path=retry_chunk_path,
                chunk=absolute_chunk,
                chunk_config=parent_chunk_config,
                covered_until=covered_until,
                total_duration=total_duration,
                segment_count=segment_count + len(recovered_segments),
                latest_text=latest_text,
                progress_callback=progress_callback,
            )
            retry_max_new_tokens = self._resolve_max_new_tokens(
                get_settings(),
                audio_duration=float(retry_chunk.duration),
            )
            retry_payload = await self._post_chunk_transcribe_request(
                chunk_path=retry_chunk_path,
                chunk=absolute_chunk,
                context=context,
                max_new_tokens=retry_max_new_tokens,
                timeout=httpx.Timeout(float(parent_chunk_config.request_timeout_sec), connect=30.0),
                chunk_config=parent_chunk_config,
                covered_until=covered_until,
                total_duration=total_duration,
                segment_count=segment_count + len(recovered_segments),
                latest_text=latest_text,
                progress_callback=progress_callback,
            )
            payloads.append(payload_to_dict(retry_payload))
            retry_result = self._build_result_from_payload(
                retry_payload,
                audio_path=retry_chunk_path,
                language=language,
                context=context,
                progress_callback=None,
            )
            local_segments, local_emitted_end = merge_chunk_result_segments(
                retry_result,
                chunk=retry_chunk,
                start_index=local_next_index,
                emitted_end=local_emitted_end,
            )
            recovered_segments.extend(local_segments)
            local_next_index += len(local_segments)
        return TranscriptResult(
            segments=recovered_segments,
            language=language,
            duration=float(parent_chunk.duration),
            provider="local_http_asr",
            model=self._model_name,
            raw_payload={
                "anchor_recovery": {
                    "parent_start": round(float(parent_chunk.start), 3),
                    "parent_end": round(float(parent_chunk.end), 3),
                    "retry_chunk_count": len(retry_specs),
                }
            },
            raw_segments=list(recovered_segments),
            context=context,
            hotword=context,
        ), payloads

    async def _export_chunk_audio(
        self,
        *,
        audio_path: Path,
        chunk_path: Path,
        chunk,
        chunk_config,
        covered_until: float,
        total_duration: float,
        segment_count: int,
        latest_text: str,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> None:
        if progress_callback is not None:
            progress_callback(
                chunk_progress_payload(
                    chunk=chunk,
                    covered_until=covered_until,
                    total_duration=total_duration,
                    segment_count=segment_count,
                    text=latest_text,
                    phase="export",
                    detail=f"导出 chunk {chunk.index + 1}/{chunk.count} 音频片段",
                )
            )
        await asyncio.to_thread(
            export_audio_chunk,
            audio_path,
            chunk_path,
            start=chunk.start,
            end=chunk.end,
            timeout_sec=float(chunk_config.export_timeout_sec),
        )

    def _should_retry_chunk_for_anchor_recovery(
        self,
        *,
        chunk_result: TranscriptResult,
        chunk,
        chunk_path: Path,
    ) -> bool:
        if "qwen3-asr" not in str(self._model_name or "").strip().lower():
            return False
        chunk_duration = max(0.0, float(chunk.duration))
        if chunk_duration < self._QWEN3_ASR_RETRY_CHUNK_SEC:
            return False
        covered_end = self._covered_end_seconds(chunk_result)
        tail_gap = max(0.0, chunk_duration - covered_end)
        if not chunk_result.segments:
            return not self._tail_is_mostly_silence(chunk_path, start=max(0.0, chunk_duration - 8.0), end=chunk_duration)
        if tail_gap < max(self._QWEN3_ASR_TAIL_GAP_MIN_SEC, chunk_duration * self._QWEN3_ASR_TAIL_GAP_MIN_RATIO):
            return False
        return self._tail_has_voiced_audio(chunk_path, start=covered_end, end=chunk_duration)

    def _covered_end_seconds(self, result: TranscriptResult) -> float:
        covered = 0.0
        for segment in list(result.segments or []):
            covered = max(covered, float(getattr(segment, "end", 0.0) or 0.0))
            for word in list(getattr(segment, "words", None) or []):
                covered = max(covered, float(getattr(word, "end", 0.0) or 0.0))
        return round(max(0.0, covered), 3)

    def _tail_has_voiced_audio(self, chunk_path: Path, *, start: float, end: float) -> bool:
        tail_duration = max(0.0, float(end) - float(start))
        if tail_duration <= 0.25:
            return False
        if tail_duration <= self._QWEN3_ASR_VOICED_TAIL_MIN_SEC:
            return True
        return not self._tail_is_mostly_silence(chunk_path, start=start, end=end)

    def _tail_is_mostly_silence(self, chunk_path: Path, *, start: float, end: float) -> bool:
        window_start = max(0.0, float(start))
        window_end = max(window_start, float(end))
        if window_end <= window_start + 0.15:
            return True
        try:
            silences = detect_silence(
                chunk_path,
                aggressiveness=2,
                frame_duration_ms=30,
                min_silence_duration_ms=180,
                padding_ms=30,
            )
        except Exception:
            return False
        covered_silence = 0.0
        for silence in silences:
            overlap_start = max(window_start, float(silence.start))
            overlap_end = min(window_end, float(silence.end))
            if overlap_end > overlap_start:
                covered_silence += overlap_end - overlap_start
        return covered_silence >= (window_end - window_start) * 0.72

    def _resolve_hotword_context(self, prompt: str | None) -> str | None:
        if not self._hotwords_enabled:
            return None
        text = str(prompt or "").strip()
        if not text:
            return None
        hotwords = extract_prompt_hotwords(text)
        if hotwords:
            return ", ".join(hotwords[:16])
        return text[:160]

    def _resolve_effective_chunk_config(self, chunk_config):
        if not self._decode_loop_sanitizer_enabled():
            return chunk_config
        chunk_size = min(float(chunk_config.chunk_size_sec), self._QWEN3_ASR_MAX_CHUNK_SEC)
        if chunk_size >= float(chunk_config.chunk_size_sec):
            return chunk_config
        min_chunk = min(float(chunk_config.min_chunk_sec), chunk_size)
        overlap = min(float(chunk_config.overlap_sec), max(0.0, chunk_size - min_chunk))
        return replace(
            chunk_config,
            chunk_size_sec=chunk_size,
            min_chunk_sec=min_chunk,
            overlap_sec=overlap,
        )

    def _resolve_max_new_tokens(self, settings: object, *, audio_duration: float) -> int:
        configured = int(getattr(settings, "local_asr_max_new_tokens", 256) or 256)
        configured = max(32, configured)
        if "qwen3-asr" not in str(self._model_name or "").strip().lower():
            return configured
        duration = max(0.0, float(audio_duration or 0.0))
        # Qwen3-ASR is sensitive to dense long-form Mandarin. Use a staged
        # budget that tracks chunk duration, then let the decode-loop sanitizer
        # catch pathological repetition.
        if duration <= 35.0:
            target = self._QWEN3_ASR_MIN_MAX_NEW_TOKENS
        elif duration <= 60.0:
            target = self._QWEN3_ASR_MID_MAX_NEW_TOKENS
        else:
            target = self._QWEN3_ASR_MAX_MAX_NEW_TOKENS
        return min(max(configured, target), self._QWEN3_ASR_MAX_MAX_NEW_TOKENS)

    async def _post_chunk_transcribe_request(
        self,
        *,
        chunk_path: Path,
        chunk,
        context: str | None,
        max_new_tokens: int,
        timeout: httpx.Timeout,
        chunk_config,
        covered_until: float,
        total_duration: float,
        segment_count: int,
        latest_text: str,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> dict[str, Any]:
        max_attempts = max(1, int(chunk_config.request_max_retries) + 1)
        for attempt in range(1, max_attempts + 1):
            if progress_callback is not None:
                progress_callback(
                    chunk_progress_payload(
                        chunk=chunk,
                        covered_until=covered_until,
                        total_duration=total_duration,
                        segment_count=segment_count,
                        text=latest_text,
                        phase="request",
                        detail=(
                            f"提交 chunk {chunk.index + 1}/{chunk.count} 转写请求"
                            if attempt == 1
                            else f"重试 chunk {chunk.index + 1}/{chunk.count} 转写请求（{attempt}/{max_attempts}）"
                        ),
                        retry_attempt=attempt,
                        retry_count=max_attempts,
                    )
                )
            try:
                return await self._post_transcribe_request(
                    chunk_path,
                    context=context,
                    max_new_tokens=max_new_tokens,
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError):
                if attempt >= max_attempts:
                    raise
                backoff_sec = float(chunk_config.request_retry_backoff_sec) * (2 ** (attempt - 1))
                if progress_callback is not None:
                    progress_callback(
                        chunk_progress_payload(
                            chunk=chunk,
                            covered_until=covered_until,
                            total_duration=total_duration,
                            segment_count=segment_count,
                            text=latest_text,
                            phase="retry_wait",
                            detail=(
                                f"chunk {chunk.index + 1}/{chunk.count} 请求失败，"
                                f"{backoff_sec:.0f}s 后重试"
                            ),
                            retry_attempt=attempt,
                            retry_count=max_attempts,
                        )
                    )
                await asyncio.sleep(backoff_sec)
        raise RuntimeError("chunk request retry loop exhausted unexpectedly")

    async def _post_transcribe_request(
        self,
        audio_path: Path,
        *,
        context: str | None,
        max_new_tokens: int,
        timeout: httpx.Timeout,
    ) -> dict[str, Any]:
        with audio_path.open("rb") as audio_file:
            files = {
                "file": (
                    audio_path.name,
                    audio_file,
                    "application/octet-stream",
                )
            }
            data = self._build_request_data(context=context, max_new_tokens=max_new_tokens)
            async with hold_managed_gpu_services_async(
                required_urls=[self._base_url],
                reason="local_http_asr_transcribe",
            ):
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self._base_url}{self._transcribe_path}", files=files, data=data)
        response.raise_for_status()
        return dict(response.json() or {})

    def _build_request_data(self, *, context: str | None, max_new_tokens: int) -> dict[str, str]:
        return {
            self._hotwords_field: context or "",
            "model": self._model_name,
            "model_name": self._model_name,
            "max_new_tokens": str(max_new_tokens),
            "beam_size": str(self._beam_size),
            "best_of": str(self._best_of),
            "condition_on_previous_text": str(self._condition_on_previous_text).lower(),
            "vad_filter": str(self._vad_filter).lower(),
        }

    def _build_result_from_payload(
        self,
        payload: dict[str, Any],
        *,
        audio_path: Path,
        language: str,
        context: str | None,
        progress_callback: TranscriptionProgressCallback | None,
    ) -> TranscriptResult:
        raw_items = self._extract_segment_items(payload)
        duration = self._resolve_duration(payload, audio_path=audio_path, raw_items=raw_items)
        segments = self._build_segments(raw_items, duration=duration, context=context)
        if not segments:
            text = str(payload.get("text") or "").strip()
            if text:
                segments = [
                    TranscriptSegment(
                        index=0,
                        start=0.0,
                        end=round(duration, 3),
                        text=text,
                        provider="local_http_asr",
                        model=self._model_name,
                        raw_payload=payload_to_dict(payload),
                        raw_text=text,
                        context=context,
                        hotword=context,
                    )
                ]

        segments = self._sanitize_asr_decode_artifacts(segments)
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
            language=language,
            duration=duration,
            provider="local_http_asr",
            model=self._model_name,
            raw_payload=payload_to_dict(payload),
            raw_segments=raw_segments_copy,
            context=context,
            hotword=context,
        )

    def _sanitize_asr_decode_artifacts(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        cleaned = list(segments or [])
        if self._decode_loop_sanitizer_enabled():
            cleaned = self._sanitize_decode_loop_segments(cleaned)
        if self._short_duplicate_noise_sanitizer_enabled():
            cleaned = self._sanitize_short_duplicate_noise_segments(cleaned)
        return cleaned

    def _extract_segment_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_segments = payload.get("segments")
        text_candidates: list[str] = []
        payload_text = str(payload.get("text") or "").strip()
        if payload_text:
            text_candidates.append(payload_text)
        if isinstance(raw_segments, list) and raw_segments:
            for item in raw_segments:
                if not isinstance(item, dict):
                    continue
                for key in ("raw_text", "text", "Content", "content"):
                    value = str(item.get(key) or "").strip()
                    if value:
                        text_candidates.append(value)
            joined_text = "".join(
                str(item.get("text") or item.get("Content") or item.get("content") or "")
                for item in raw_segments
                if isinstance(item, dict)
            ).strip()
            if joined_text:
                text_candidates.append(joined_text)

        for text in text_candidates:
            parsed_items = self._parse_segment_items_from_text(text)
            if parsed_items:
                return parsed_items

        if isinstance(raw_segments, list) and raw_segments:
            return [dict(item) for item in raw_segments if isinstance(item, dict)]
        return []

    def _parse_segment_items_from_text(self, text: str) -> list[dict[str, Any]]:
        candidates = self._segment_text_candidates(text)
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            for _ in range(2):
                if isinstance(parsed, str):
                    try:
                        parsed = json.loads(parsed.strip())
                    except json.JSONDecodeError:
                        break
                    continue
                break
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return [dict(item) for item in parsed if isinstance(item, dict)]
            loose_items = self._parse_loose_segment_stream(candidate)
            if loose_items:
                return loose_items
        for candidate in candidates:
            loose_items = self._parse_loose_segment_stream(candidate)
            if loose_items:
                return loose_items
        return []

    def _segment_text_candidates(self, text: str) -> list[str]:
        normalized = str(text or "").strip()
        if not normalized:
            return []
        candidates = [normalized]
        if "\\\"" in normalized:
            candidates.append(normalized.replace("\\\"", "\""))
        if "\\n" in normalized or "\\t" in normalized:
            try:
                candidates.append(bytes(normalized, "utf-8").decode("unicode_escape"))
            except UnicodeDecodeError:
                pass
        for candidate in list(candidates):
            extracted = self._extract_json_container(candidate)
            if extracted and extracted not in candidates:
                candidates.append(extracted)
        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _extract_json_container(text: str) -> str | None:
        value = str(text or "").strip()
        starts = [index for index in (value.find("["), value.find("{")) if index >= 0]
        if not starts:
            return None
        start = min(starts)
        opener = value[start]
        closer = "]" if opener == "[" else "}"
        end = value.rfind(closer)
        if end <= start:
            return None
        return value[start : end + 1].strip()

    def _parse_loose_segment_stream(self, text: str) -> list[dict[str, Any]]:
        value = self._repair_loose_segment_json(text)
        if not value:
            return []
        objects = self._extract_complete_json_objects(value)
        parsed_items: list[dict[str, Any]] = []
        for obj_text in objects:
            try:
                parsed = json.loads(obj_text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                parsed_items.append(parsed)
        return parsed_items

    @staticmethod
    def _repair_loose_segment_json(text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        starts = [index for index in (value.find("["), value.find("{")) if index >= 0]
        if starts:
            value = value[min(starts) :]
        value = re.sub(r'(?<=\d)(?="(?:Start|End|Speaker|Content)"\s*:)', ",", value)
        value = re.sub(r'(?<=\})(?=\{)', ",", value)
        return value

    @staticmethod
    def _extract_complete_json_objects(text: str) -> list[str]:
        objects: list[str] = []
        depth = 0
        start: int | None = None
        in_string = False
        escaped = False
        for index, char in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
                continue
            if char == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start : index + 1])
                    start = None
        return objects

    def _build_segments(
        self,
        raw_items: list[dict[str, Any]],
        *,
        duration: float,
        context: str | None,
    ) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for item in raw_items:
            text = str(item.get("text") or item.get("Content") or item.get("content") or "").strip()
            if not text:
                continue
            start = self._coerce_time(item.get("start_time", item.get("Start", item.get("start"))), default=0.0)
            end = self._coerce_time(item.get("end_time", item.get("End", item.get("end"))), default=start)
            if duration > 0 and end <= start and len(raw_items) == 1:
                end = duration
            speaker_value = item.get("speaker_id", item.get("Speaker", item.get("speaker")))
            speaker = None if speaker_value is None else str(speaker_value)
            words = self._build_word_timings(item, context=context)
            segments.append(
                TranscriptSegment(
                    index=len(segments),
                    start=max(0.0, start),
                    end=max(start, end),
                    text=text,
                    words=words,
                    speaker=speaker,
                    provider="local_http_asr",
                    model=self._model_name,
                    raw_payload=dict(item),
                    raw_text=text,
                    context=context,
                )
            )
        return segments

    def _build_word_timings(self, item: dict[str, Any], *, context: str | None) -> list[WordTiming]:
        raw_words = item.get("words")
        if raw_words is None:
            raw_words = item.get("word_or_char_timestamps")
        if raw_words is None:
            raw_words = item.get("timestamps")
        if not isinstance(raw_words, list):
            return []
        words: list[WordTiming] = []
        for raw in raw_words:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("word") or raw.get("text") or raw.get("char") or "").strip()
            if not text:
                continue
            start = self._coerce_time(raw.get("start_time", raw.get("start")), default=0.0)
            end = self._coerce_time(raw.get("end_time", raw.get("end")), default=start)
            words.append(
                WordTiming(
                    word=text,
                    start=max(0.0, start),
                    end=max(start, end),
                    provider="local_http_asr",
                    model=self._model_name,
                    raw_payload=dict(raw),
                    raw_text=text,
                    context=context,
                    hotword=context,
                )
            )
        return words

    def _sanitize_decode_loop_segments(
        self,
        segments: list[TranscriptSegment],
        *,
        repeated_segment_strategy: str = "collapse",
        repeated_segment_min_repeats: int | None = None,
    ) -> list[TranscriptSegment]:
        cleaned_segments = [
            self._copy_segment_with_text(segment, text=self._collapse_decode_loop_text(segment.text))
            for segment in list(segments or [])
        ]
        min_repeats = max(2, int(repeated_segment_min_repeats or self._DECODE_LOOP_MIN_REPEATS))
        if repeated_segment_strategy == "drop":
            cleaned_segments = self._drop_repeated_decode_loop_segment_sequences(
                cleaned_segments,
                min_repeats=min_repeats,
            )
        collapsed: list[TranscriptSegment] = []
        index = 0
        while index < len(cleaned_segments):
            current = cleaned_segments[index]
            current_key = self._decode_loop_key(current.text)
            run_end = index + 1
            while run_end < len(cleaned_segments):
                next_key = self._decode_loop_key(cleaned_segments[run_end].text)
                if not current_key or next_key != current_key:
                    break
                run_end += 1

            run_length = run_end - index
            if self._is_decode_loop_key(current_key) and run_length >= min_repeats:
                run = cleaned_segments[index:run_end]
                first = run[0]
                merged = self._copy_segment_with_text(first, text=first.text)
                merged.raw_payload = dict(merged.raw_payload)
                filtering = self._filtering_payload(merged.raw_payload)
                if repeated_segment_strategy == "drop":
                    merged.raw_payload["_roughcut_filtering"] = {
                        **filtering,
                        "dropped_decode_loop_segments": {
                            "repeat_count": run_length,
                            "dropped_count": run_length - 1,
                            "kept_start": round(float(first.start), 3),
                            "kept_end": round(float(first.end), 3),
                            "dropped_start": round(float(run[1].start), 3),
                            "dropped_end": round(max(float(item.end) for item in run[1:]), 3),
                            "text": first.text,
                        },
                    }
                else:
                    merged.end = round(max(float(item.end) for item in run), 3)
                    merged.raw_payload["_roughcut_filtering"] = {
                        **filtering,
                        "collapsed_decode_loop_segments": {
                            "repeat_count": run_length,
                            "start": round(float(run[0].start), 3),
                            "end": round(float(merged.end), 3),
                            "text": first.text,
                        },
                    }
                collapsed.append(merged)
            else:
                collapsed.extend(cleaned_segments[index:run_end])
            index = run_end

        return [
            TranscriptSegment(
                index=new_index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                words=list(segment.words),
                speaker=segment.speaker,
                provider=segment.provider,
                model=segment.model,
                raw_payload=dict(segment.raw_payload),
                raw_text=segment.raw_text,
                context=segment.context,
                hotword=segment.hotword,
                confidence=segment.confidence,
                logprob=segment.logprob,
                alignment=segment.alignment,
            )
            for new_index, segment in enumerate(collapsed)
            if str(segment.text or "").strip()
        ]

    def _drop_repeated_decode_loop_segment_sequences(
        self,
        segments: list[TranscriptSegment],
        *,
        min_repeats: int,
    ) -> list[TranscriptSegment]:
        source_segments = list(segments or [])
        if len(source_segments) < min_repeats:
            return source_segments

        keys = [self._decode_loop_key(segment.text) for segment in source_segments]
        filtered: list[TranscriptSegment] = []
        index = 0
        while index < len(source_segments):
            remaining = len(source_segments) - index
            best_pattern_len = 0
            best_repeat_count = 0
            max_pattern_len = min(6, remaining // min_repeats)
            for pattern_len in range(1, max_pattern_len + 1):
                pattern_keys = keys[index : index + pattern_len]
                pattern_key = "".join(pattern_keys)
                if not self._is_decode_loop_key(pattern_key):
                    continue
                repeat_count = 1
                cursor = index + pattern_len
                while cursor + pattern_len <= len(source_segments) and keys[cursor : cursor + pattern_len] == pattern_keys:
                    repeat_count += 1
                    cursor += pattern_len
                if repeat_count >= min_repeats and pattern_len * repeat_count > best_pattern_len * best_repeat_count:
                    best_pattern_len = pattern_len
                    best_repeat_count = repeat_count

            if best_pattern_len > 0:
                kept = [
                    self._copy_segment_with_text(segment, text=segment.text)
                    for segment in source_segments[index : index + best_pattern_len]
                ]
                dropped = source_segments[index + best_pattern_len : index + best_pattern_len * best_repeat_count]
                first = kept[0]
                first.raw_payload = dict(first.raw_payload)
                first.raw_payload["_roughcut_filtering"] = {
                    **self._filtering_payload(first.raw_payload),
                    "dropped_decode_loop_segment_sequences": {
                        "repeat_count": best_repeat_count,
                        "pattern_segment_count": best_pattern_len,
                        "dropped_count": len(dropped),
                        "kept_start": round(float(kept[0].start), 3),
                        "kept_end": round(float(kept[-1].end), 3),
                        "dropped_start": round(float(dropped[0].start), 3) if dropped else None,
                        "dropped_end": round(max((float(item.end) for item in dropped), default=float(kept[-1].end)), 3),
                        "text": "".join(segment.text for segment in kept),
                    },
                }
                filtered.extend(kept)
                index += best_pattern_len * best_repeat_count
                continue

            filtered.append(source_segments[index])
            index += 1
        return filtered

    def _copy_segment_with_text(self, segment: TranscriptSegment, *, text: str) -> TranscriptSegment:
        cleaned = str(text or "").strip()
        raw_text = segment.raw_text or segment.text
        raw_payload = dict(segment.raw_payload)
        if cleaned and cleaned != str(segment.text or "").strip():
            raw_payload["_roughcut_filtering"] = {
                **self._filtering_payload(raw_payload),
                "collapsed_decode_loop_text": {
                    "original_text": segment.text,
                    "text": cleaned,
                },
            }
        return TranscriptSegment(
            index=segment.index,
            start=segment.start,
            end=segment.end,
            text=cleaned,
            words=list(segment.words),
            speaker=segment.speaker,
            provider=segment.provider,
            model=segment.model,
            raw_payload=raw_payload,
            raw_text=raw_text,
            context=segment.context,
            hotword=segment.hotword,
            confidence=segment.confidence,
            logprob=segment.logprob,
            alignment=segment.alignment,
        )

    def _decode_loop_sanitizer_enabled(self) -> bool:
        return "qwen3-asr" in str(self._model_name or "").strip().lower()

    def _short_duplicate_noise_sanitizer_enabled(self) -> bool:
        model_name = str(self._model_name or "").strip().lower()
        return any(
            marker in model_name
            for marker in (
                "qwen3-asr",
                "fun-asr-nano",
                "fun_asr_nano",
                "funasr-nano",
                "funasr_nano",
            )
        )

    @staticmethod
    def _filtering_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
        filtering = raw_payload.get("_roughcut_filtering")
        return dict(filtering) if isinstance(filtering, dict) else {}

    def _sanitize_short_duplicate_noise_segments(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        sanitized: list[TranscriptSegment] = []
        for index, segment in enumerate(list(segments or [])):
            text, collapsed_text_loop_count = self._collapse_short_duplicate_noise_text(
                segment.text,
                allow_long_text_loops=not bool(segment.words),
            )
            words, dropped_word_count = self._collapse_short_duplicate_noise_words(segment.words)
            text_changed = text != str(segment.text or "").strip()
            words_changed = words != list(segment.words)
            if words_changed and not text_changed:
                rebuilt_text = "".join(str(word.word or "").strip() for word in words).strip()
                if rebuilt_text:
                    text = rebuilt_text
                    text_changed = text != str(segment.text or "").strip()
            raw_payload = dict(segment.raw_payload)
            if text_changed or words_changed:
                raw_payload["_roughcut_filtering"] = {
                    **self._filtering_payload(raw_payload),
                    "collapsed_short_duplicate_noise": {
                        "original_text": segment.text,
                        "text": text,
                        "dropped_word_count": dropped_word_count,
                        "collapsed_text_loop_count": collapsed_text_loop_count,
                    },
                }
            sanitized.append(
                TranscriptSegment(
                    index=index,
                    start=segment.start,
                    end=segment.end,
                    text=text,
                    words=words,
                    speaker=segment.speaker,
                    provider=segment.provider,
                    model=segment.model,
                    raw_payload=raw_payload,
                    raw_text=segment.raw_text or segment.text,
                    context=segment.context,
                    hotword=segment.hotword,
                    confidence=segment.confidence,
                    logprob=segment.logprob,
                    alignment=segment.alignment,
                )
            )
        return [segment for segment in sanitized if str(segment.text or "").strip()]

    @classmethod
    def _collapse_short_duplicate_noise_text(
        cls,
        text: str,
        *,
        allow_long_text_loops: bool = True,
    ) -> tuple[str, int]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return "", 0
        collapsed_text_loop_count = 0
        cleaned = re.sub(r"没(?:没有)+", "没有", cleaned)
        cleaned = re.sub(r"(?:没有){2,}", "没有", cleaned)
        cleaned = re.sub(r"这(?=这个)", "", cleaned)
        cleaned = re.sub(r"那(?=那个)", "", cleaned)
        cleaned = cls._SHORT_PREFIX_DUPLICATE_NOISE_RE.sub(r"\1", cleaned)
        cleaned = cls._SHORT_DUPLICATE_NOISE_RE.sub(r"\1", cleaned)
        if allow_long_text_loops:
            cleaned, collapsed_text_loop_count = cls._collapse_long_text_only_duplicate_loops(cleaned)
        return cleaned.strip(), collapsed_text_loop_count

    @classmethod
    def _collapse_long_text_only_duplicate_loops(cls, text: str) -> tuple[str, int]:
        dropped_count = 0

        def keep_pair(match: re.Match[str]) -> str:
            nonlocal dropped_count
            value = match.group(0)
            dropped_count += max(0, len(value) - 2)
            return match.group(1) * 2

        def keep_single(match: re.Match[str]) -> str:
            nonlocal dropped_count
            value = match.group(0)
            dropped_count += max(0, len(value) - 1)
            return match.group(1)

        cleaned = cls._LONG_LAUGHTER_DUPLICATE_NOISE_RE.sub(keep_pair, str(text or ""))
        cleaned = cls._LONG_CJK_DUPLICATE_NOISE_RE.sub(keep_single, cleaned)
        return cleaned, dropped_count

    def _collapse_short_duplicate_noise_words(self, words: list[WordTiming]) -> tuple[list[WordTiming], int]:
        source = list(words or [])
        if not source:
            return [], 0

        cleaned: list[WordTiming] = []
        dropped_count = 0
        index = 0
        while index < len(source):
            word = source[index]
            key = self._short_duplicate_noise_key(word.word)

            if key == "没" and index + 1 < len(source) and self._short_duplicate_noise_key(source[index + 1].word) == "没有":
                end_index = index + 2
                while end_index < len(source) and self._short_duplicate_noise_key(source[end_index].word) == "没有":
                    end_index += 1
                kept = self._copy_word_timing(source[index + 1], word_text="没有", start=word.start)
                cleaned.append(kept)
                dropped_count += end_index - index - 1
                index = end_index
                continue

            if key == "没有":
                run_end = index + 1
                while run_end < len(source) and self._short_duplicate_noise_key(source[run_end].word) == "没有":
                    run_end += 1
                cleaned.append(self._copy_word_timing(word))
                dropped_count += run_end - index - 1
                index = run_end
                continue

            if key in {"这", "那"} and index + 1 < len(source):
                next_key = self._short_duplicate_noise_key(source[index + 1].word)
                if next_key == f"{key}个":
                    cleaned.append(self._copy_word_timing(source[index + 1], start=word.start))
                    dropped_count += 1
                    index += 2
                    continue

            if key in self._SHORT_PREFIX_DUPLICATE_NOISE_TERMS and index + 1 < len(source):
                next_key = self._short_duplicate_noise_key(source[index + 1].word)
                if next_key == key or next_key.startswith(key):
                    cleaned.append(self._copy_word_timing(source[index + 1], start=word.start))
                    dropped_count += 1
                    index += 2
                    continue

            if key in self._SHORT_DUPLICATE_NOISE_TERMS:
                run_end = index + 1
                while run_end < len(source) and self._short_duplicate_noise_key(source[run_end].word) == key:
                    run_end += 1
                cleaned.append(self._copy_word_timing(word))
                dropped_count += run_end - index - 1
                index = run_end
                continue

            run_end = index + 1
            while run_end < len(source) and self._short_duplicate_noise_key(source[run_end].word) == key:
                run_end += 1
            if run_end > index + 1 and self._duplicate_word_run_has_collapsed_timing(source[index:run_end]):
                cleaned.append(self._copy_word_timing(word))
                dropped_count += run_end - index - 1
                index = run_end
                continue

            cleaned.append(self._copy_word_timing(word))
            index += 1

        return cleaned, dropped_count

    @staticmethod
    def _duplicate_word_run_has_collapsed_timing(words: list[WordTiming]) -> bool:
        if len(words) <= 1:
            return False
        starts = [float(getattr(word, "start", 0.0) or 0.0) for word in words]
        ends = [float(getattr(word, "end", starts[index]) or starts[index]) for index, word in enumerate(words)]
        durations = [max(0.0, end - start) for start, end in zip(starts, ends)]
        span = max(ends) - min(starts) if starts and ends else 0.0
        unique_starts = {round(value, 2) for value in starts}
        return len(unique_starts) <= 1 or (span <= 0.16 and any(duration <= 0.025 for duration in durations))

    @classmethod
    def _short_duplicate_noise_key(cls, text: str) -> str:
        return cls._decode_loop_key(text)

    @staticmethod
    def _copy_word_timing(
        word: WordTiming,
        *,
        word_text: str | None = None,
        start: float | None = None,
        end: float | None = None,
    ) -> WordTiming:
        return WordTiming(
            word=word.word if word_text is None else word_text,
            start=word.start if start is None else start,
            end=word.end if end is None else end,
            provider=word.provider,
            model=word.model,
            raw_payload=dict(word.raw_payload),
            raw_text=word.raw_text,
            context=word.context,
            hotword=word.hotword,
            confidence=word.confidence,
            logprob=word.logprob,
            alignment=word.alignment,
        )

    def _collapse_decode_loop_text(self, text: str) -> str:
        original = str(text or "").strip()
        phrases = self._sentence_like_phrases(text)
        if len(phrases) < self._DECODE_LOOP_MIN_REPEATS:
            return self._collapse_compact_decode_loop_text(original)

        collapsed: list[str] = []
        index = 0
        changed = False
        while index < len(phrases):
            key = self._decode_loop_key(phrases[index])
            run_end = index + 1
            while run_end < len(phrases) and key and self._decode_loop_key(phrases[run_end]) == key:
                run_end += 1
            run_length = run_end - index
            if self._is_decode_loop_key(key) and run_length >= self._DECODE_LOOP_MIN_REPEATS:
                collapsed.append(phrases[index])
                changed = True
            else:
                collapsed.extend(phrases[index:run_end])
            index = run_end

        return "".join(collapsed).strip() if changed else self._collapse_compact_decode_loop_text(original)

    @classmethod
    def _collapse_compact_decode_loop_text(cls, text: str) -> str:
        original = str(text or "").strip()
        compact = cls._decode_loop_key(original)
        max_unit_length = len(compact) // cls._DECODE_LOOP_MIN_REPEATS
        if max_unit_length < cls._DECODE_LOOP_MIN_TEXT_UNITS:
            return original
        for unit_length in range(cls._DECODE_LOOP_MIN_TEXT_UNITS, max_unit_length + 1):
            unit = compact[:unit_length]
            cursor = 0
            repeat_count = 0
            while compact.startswith(unit, cursor):
                repeat_count += 1
                cursor += unit_length
            remainder = len(compact) - cursor
            if repeat_count >= cls._DECODE_LOOP_MIN_REPEATS and remainder <= max(2, unit_length // 4):
                return cls._slice_original_text_by_compact_units(original, unit_length)
        return original

    @classmethod
    def _slice_original_text_by_compact_units(cls, text: str, compact_units: int) -> str:
        seen_units = 0
        end_index = 0
        for index, char in enumerate(str(text or "")):
            if cls._decode_loop_key(char):
                seen_units += 1
            if seen_units >= compact_units:
                end_index = index + 1
                break
        value = str(text or "")[:end_index]
        while end_index < len(text) and not cls._decode_loop_key(text[end_index]):
            value += text[end_index]
            end_index += 1
        return value.strip()

    @classmethod
    def _sentence_like_phrases(cls, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return []
        return [
            match.group(0).strip()
            for match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", normalized)
            if match.group(0).strip()
        ]

    @classmethod
    def _decode_loop_key(cls, text: str) -> str:
        return re.sub(r"[\s\u3000，,。！？!?；;：:、\"'“”‘’()\[\]{}<>《》]+", "", str(text or "")).strip()

    @classmethod
    def _is_decode_loop_key(cls, key: str) -> bool:
        return len(str(key or "")) >= cls._DECODE_LOOP_MIN_TEXT_UNITS

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
        has_provider_words = bool(repaired[0].words)
        if (
            len(repaired) == 1
            and duration > 1.0
            and not has_provider_words
            and (missing_timing or self._text_units(repaired[0].text) >= 28)
        ):
            return self._split_long_segment(repaired[0], duration=duration)
        return repaired

    def _split_long_segment(self, segment: TranscriptSegment, *, duration: float) -> list[TranscriptSegment]:
        chunks = self._split_text_chunks(segment.text)
        if len(chunks) <= 1:
            segment.end = round(max(duration, segment.end), 3)
            return [segment]
        total_units = sum(max(1, self._text_units(chunk)) for chunk in chunks)
        target_start = max(0.0, float(segment.start))
        target_end = max(target_start, float(duration), float(segment.end))
        target_duration = max(0.0, target_end - target_start)
        cursor = target_start
        split_segments: list[TranscriptSegment] = []
        for index, chunk in enumerate(chunks):
            weight = max(1, self._text_units(chunk))
            chunk_duration = target_duration * weight / total_units if total_units > 0 else 0.0
            end = target_end if index == len(chunks) - 1 else min(target_end, cursor + chunk_duration)
            split_segments.append(
                TranscriptSegment(
                    index=index,
                    start=round(cursor, 3),
                    end=round(max(cursor, end), 3),
                    text=chunk,
                    speaker=segment.speaker,
                    provider=segment.provider,
                    model=segment.model,
                    raw_payload=dict(segment.raw_payload),
                    raw_text=segment.raw_text or segment.text,
                    context=segment.context,
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
    def _normalize_path(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "/"
        return text if text.startswith("/") else f"/{text}"

    @staticmethod
    def _text_units(text: str) -> int:
        return len(re.sub(r"\s+", "", text))

    @staticmethod
    def _coerce_time(value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _resolve_duration(self, payload: dict[str, Any], *, audio_path: Path, raw_items: list[dict[str, Any]]) -> float:
        for key in ("duration", "duration_seconds"):
            try:
                duration = float(payload.get(key) or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                return duration
        end_times = [
            self._coerce_time(item.get("end_time", item.get("End", item.get("end"))), default=0.0)
            for item in raw_items
        ]
        if end_times and max(end_times) > 0:
            return max(end_times)
        return probe_audio_duration(audio_path)
