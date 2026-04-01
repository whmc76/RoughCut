from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float
    box: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class OCRFrameResult:
    frame_index: int
    timestamp: float
    lines: list[OCRLine] = field(default_factory=list)
    frame_path: str | None = None


@dataclass(slots=True)
class OCRResult:
    provider: str
    available: bool
    status: str
    frames: list[OCRFrameResult] = field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class OCRProvider(ABC):
    @abstractmethod
    async def recognize_frames(
        self,
        frame_paths: Sequence[Path],
        *,
        language: str = "zh-CN",
    ) -> OCRResult:
        """Recognize text from sampled video frames."""
