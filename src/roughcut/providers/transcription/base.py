from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    words: list[WordTiming] = field(default_factory=list)
    speaker: str | None = None


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float


class TranscriptionProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path, *, language: str = "zh-CN") -> TranscriptResult:
        """Transcribe audio file and return structured result."""
