from __future__ import annotations

from pathlib import Path
from typing import Any

from roughcut.providers.voice.base import VoiceProvider


class EdgeTtsVoiceProvider(VoiceProvider):
    def build_dubbing_request(
        self,
        *,
        job_id: str,
        segments: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "provider": "edge",
            "job_id": job_id,
            "mode": "fast_tts",
            "segment_count": len(segments),
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "text": segment.get("rewritten_text") or segment.get("script") or segment.get("source_text"),
                    "target_duration_sec": segment.get("target_duration_sec"),
                }
                for segment in segments
            ],
            "metadata": metadata or {},
        }

    def execute_dubbing(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
        reference_audio_path: Path | None = None,
    ) -> dict[str, Any]:
        del reference_audio_path
        return {
            "provider": "edge",
            "job_id": job_id,
            "status": "planning_only",
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "status": "planned",
                    "text": segment.get("text"),
                    "target_duration_sec": segment.get("target_duration_sec"),
                }
                for segment in (request.get("segments") or [])
            ],
        }
