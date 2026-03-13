from __future__ import annotations

from typing import Any

from roughcut.providers.avatar.base import AvatarProvider


class MockAvatarProvider(AvatarProvider):
    def build_render_request(
        self,
        *,
        job_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": "mock",
            "job_id": job_id,
            "mode": "planning_only",
            "layout_template": plan.get("layout_template"),
            "presenter_id": plan.get("presenter_id"),
            "segment_count": len(plan.get("segments") or []),
        }

    def execute_render(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": "mock",
            "job_id": job_id,
            "status": "planning_only",
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "status": "planned",
                    "script": segment.get("script"),
                }
                for segment in (request.get("segments") or [])
            ],
        }
