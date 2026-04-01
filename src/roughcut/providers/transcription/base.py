from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class WordTiming:
    word: str
    start: float
    end: float
    provider: str | None = None
    model: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    raw_text: str | None = None
    context: str | None = None
    hotword: str | None = None
    confidence: float | None = None
    logprob: float | None = None
    alignment: Any | None = None


@dataclass
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    words: list[WordTiming] = field(default_factory=list)
    speaker: str | None = None
    provider: str | None = None
    model: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    raw_text: str | None = None
    context: str | None = None
    hotword: str | None = None
    confidence: float | None = None
    logprob: float | None = None
    alignment: Any | None = None


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float
    provider: str | None = None
    model: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    raw_segments: list[TranscriptSegment] = field(default_factory=list)
    context: str | None = None
    hotword: str | None = None
    confidence: float | None = None
    logprob: float | None = None
    alignment: Any | None = None


TranscriptionProgressCallback = Callable[[dict[str, Any]], None]


class TranscriptionProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh-CN",
        prompt: str | None = None,
        progress_callback: TranscriptionProgressCallback | None = None,
    ) -> TranscriptResult:
        """Transcribe audio file and return structured result."""


def payload_to_dict(payload: Any | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return dict(payload)
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(payload, attr, None)
        if callable(method):
            try:
                dumped = method()
            except TypeError:
                try:
                    dumped = method(mode="json")
                except TypeError:
                    continue
            if isinstance(dumped, dict):
                return dict(dumped)
    if hasattr(payload, "__dict__"):
        return {
            key: value
            for key, value in vars(payload).items()
            if not key.startswith("_")
        }
    return {"value": repr(payload)}
