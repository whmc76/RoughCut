from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AvatarProvider(ABC):
    @abstractmethod
    def build_render_request(
        self,
        *,
        job_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a provider-specific render request payload."""

    def execute_render(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a provider-specific render request."""
        return {
            "provider": request.get("provider"),
            "job_id": job_id,
            "status": "planning_only",
            "segments": [],
        }
