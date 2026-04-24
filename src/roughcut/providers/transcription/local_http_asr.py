from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
import tempfile
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async
from roughcut.providers.transcription.base import (
    TranscriptionProgressCallback,
    TranscriptResult,
    TranscriptSegment,
    TranscriptionProvider,
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
    def __init__(self, *, model_name: str = "local-asr-current") -> None:
        settings = get_settings()
        self._base_url = settings.local_asr_api_base_url.rstrip("/")
        self._transcribe_path = self._normalize_path(settings.local_asr_transcribe_path or "/transcribe")
        configured_model = str(settings.local_asr_model_name or "").strip()
        self._model_name = configured_model or model_name
        self._hotwords_field = str(settings.local_asr_hotwords_field or "hotwords").strip() or "hotwords"

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
        max_new_tokens = int(getattr(settings, "local_asr_max_new_tokens", 4096) or 4096)
        chunk_config = resolve_audio_chunk_config(settings)
        probed_duration = probe_audio_duration(audio_path)
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
                chunk_path = Path(tmpdir) / f"chunk_{chunk.start:.2f}_{chunk.end:.2f}.wav"
                if progress_callback is not None:
                    progress_callback(
                        chunk_progress_payload(
                            chunk=chunk,
                            covered_until=emitted_end,
                            total_duration=total_duration,
                            segment_count=len(segments),
                            text=segments[-1].text if segments else "",
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
                chunk_payload = await self._post_chunk_transcribe_request(
                    chunk_path=chunk_path,
                    chunk=chunk,
                    context=context,
                    max_new_tokens=max_new_tokens,
                    timeout=httpx.Timeout(float(chunk_config.request_timeout_sec), connect=30.0),
                    chunk_config=chunk_config,
                    covered_until=emitted_end,
                    total_duration=total_duration,
                    segment_count=len(segments),
                    latest_text=segments[-1].text if segments else "",
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

        raw_segments = list(segments)
        repaired_segments = self._repair_segments(segments, duration=total_duration)
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

    def _resolve_hotword_context(self, prompt: str | None) -> str | None:
        text = str(prompt or "").strip()
        if not text:
            return None
        hotwords = extract_prompt_hotwords(text)
        if hotwords:
            return ", ".join(hotwords[:16])
        return text[:160]

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
            data = {
                self._hotwords_field: context or "",
                "max_new_tokens": str(max_new_tokens),
            }
            async with hold_managed_gpu_services_async(
                required_urls=[self._base_url],
                reason="local_http_asr_transcribe",
            ):
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self._base_url}{self._transcribe_path}", files=files, data=data)
        response.raise_for_status()
        return dict(response.json() or {})

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
            segments.append(
                TranscriptSegment(
                    index=len(segments),
                    start=max(0.0, start),
                    end=max(start, end),
                    text=text,
                    speaker=speaker,
                    provider="local_http_asr",
                    model=self._model_name,
                    raw_payload=dict(item),
                    raw_text=text,
                    context=context,
                )
            )
        return segments

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
            segment.end = round(max(duration, segment.end), 3)
            return [segment]
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
