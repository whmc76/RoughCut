from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Sequence

from roughcut.providers.ocr.base import OCRFrameResult, OCRLine, OCRProvider, OCRResult


class PaddleOCRProvider(OCRProvider):
    def __init__(self, *, language: str = "ch", use_gpu: bool = False) -> None:
        self.language = language
        self.use_gpu = use_gpu
        self._engine = None
        self._availability_reason = ""

    def _load_engine(self):
        if self._engine is not None:
            return self._engine
        if importlib.util.find_spec("paddleocr") is None:
            self._availability_reason = "paddleocr dependency is unavailable"
            return None
        try:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(lang=self.language, use_angle_cls=True, use_gpu=self.use_gpu, show_log=False)
            return self._engine
        except Exception as exc:  # pragma: no cover - depends on local optional dependency
            self._availability_reason = f"paddleocr initialization failed: {exc}"
            return None

    async def recognize_frames(
        self,
        frame_paths: Sequence[Path],
        *,
        language: str = "zh-CN",
    ) -> OCRResult:
        if not frame_paths:
            return OCRResult(provider="paddleocr", available=True, status="empty", frames=[])

        engine = self._load_engine()
        if engine is None:
            return OCRResult(
                provider="paddleocr",
                available=False,
                status="unavailable",
                frames=[],
                reason=self._availability_reason or "paddleocr unavailable",
            )

        frames: list[OCRFrameResult] = []
        total_lines = 0
        for index, frame_path in enumerate(frame_paths):
            lines: list[OCRLine] = []
            try:
                raw_result = engine.ocr(str(frame_path), cls=True)
                lines = _parse_ocr_lines(raw_result)
            except Exception as exc:
                self._availability_reason = f"paddleocr inference failed for {frame_path}: {exc}"
            total_lines += len(lines)
            frames.append(
                OCRFrameResult(
                    frame_index=index,
                    timestamp=float(index),
                    lines=lines,
                    frame_path=str(frame_path),
                )
            )

        status = "ok" if total_lines else "empty"
        return OCRResult(
            provider="paddleocr",
            available=True,
            status=status,
            frames=frames,
            reason=self._availability_reason,
            metadata={"language": language},
        )


def _parse_ocr_lines(raw_result) -> list[OCRLine]:
    entries = _extract_entries(raw_result)
    lines: list[OCRLine] = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        box = _normalize_box(entry[0])
        text, confidence = _normalize_text_confidence(entry[1])
        text = text.strip()
        if not text:
            continue
        lines.append(OCRLine(text=text, confidence=confidence, box=box))
    return lines


def _extract_entries(raw_result) -> list[object]:
    if raw_result is None:
        return []
    if isinstance(raw_result, (list, tuple)):
        if _looks_like_ocr_entries(raw_result):
            return list(raw_result)
        if len(raw_result) == 1 and isinstance(raw_result[0], (list, tuple)) and _looks_like_ocr_entries(raw_result[0]):
            return list(raw_result[0])
    return list(raw_result) if isinstance(raw_result, (list, tuple)) else [raw_result]


def _looks_like_ocr_entries(value: Sequence[object]) -> bool:
    if not value:
        return False
    first = value[0]
    return isinstance(first, (list, tuple)) and len(first) >= 2


def _normalize_text_confidence(value: object) -> tuple[str, float]:
    if isinstance(value, (list, tuple)) and value:
        text = str(value[0] or "")
        confidence = float(value[1]) if len(value) > 1 else 0.0
        return text, confidence
    return str(value or ""), 0.0


def _normalize_box(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        left, top, right, bottom = value
        return float(left), float(top), float(right), float(bottom)
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        points.append((float(point[0]), float(point[1])))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)
