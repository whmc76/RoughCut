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
    capability_matrix = _extract_capability_matrix(bundle)
    orchestration_trace = _extract_orchestration_trace(bundle)
    return {
        "mainline": "content_understanding",
        "orchestrator": "content_understanding",
        "evidence_bundle": evidence_bundle,
        "capability_matrix": capability_matrix,
        "orchestration_trace": orchestration_trace,
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


def _extract_capability_matrix(bundle: dict[str, Any]) -> dict[str, Any]:
    value = bundle.get("capability_matrix")
    if isinstance(value, dict):
        return dict(value)
    nested = bundle.get("content_understanding")
    if isinstance(nested, dict) and isinstance(nested.get("capability_matrix"), dict):
        return dict(nested["capability_matrix"])
    return {}


def _extract_orchestration_trace(bundle: dict[str, Any]) -> list[str]:
    value = bundle.get("orchestration_trace")
    if isinstance(value, list):
        trace = [str(item).strip() for item in value if str(item).strip()]
        if trace:
            return trace
    nested = bundle.get("content_understanding")
    if isinstance(nested, dict) and isinstance(nested.get("orchestration_trace"), list):
        trace = [str(item).strip() for item in nested["orchestration_trace"] if str(item).strip()]
        if trace:
            return trace
    return []
