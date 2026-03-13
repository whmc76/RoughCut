from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VoiceProvider(ABC):
    @abstractmethod
    def build_dubbing_request(
        self,
        *,
        job_id: str,
        segments: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a provider-specific dubbing request payload."""

    def execute_dubbing(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
        reference_audio_path: Path | None = None,
    ) -> dict[str, Any]:
        """Execute a provider-specific dubbing request."""
        del reference_audio_path
        return {
            "provider": request.get("provider"),
            "job_id": job_id,
            "status": "planning_only",
            "segments": [],
        }
