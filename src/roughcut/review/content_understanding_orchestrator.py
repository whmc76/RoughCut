from __future__ import annotations

from typing import Any

from roughcut.review.content_understanding_evidence import normalize_evidence_bundle
from roughcut.review.content_understanding_visual import infer_visual_semantic_evidence


def build_content_understanding_orchestration_context(bundle: object | None) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise TypeError("content understanding orchestrator expects a dict evidence bundle")
    if "evidence_bundle" in bundle:
        raise ValueError("expected raw evidence input, got an already-orchestrated context")
    evidence_bundle = normalize_evidence_bundle(bundle)
    return {
        "mainline": "content_understanding",
        "orchestrator": "content_understanding",
        "evidence_bundle": evidence_bundle,
    }


async def build_visual_understanding_orchestration_context(
    *,
    frame_paths: list[Any],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    return {
        "frame_paths": list(frame_paths),
        "capabilities": capabilities,
        "visual_semantic_evidence": await infer_visual_semantic_evidence(frame_paths, capabilities),
    }
