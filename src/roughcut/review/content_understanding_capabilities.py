from __future__ import annotations

from typing import Any

from roughcut.config import CONTENT_UNDERSTANDING_CAPABILITY_SLOTS, get_settings


def resolve_content_understanding_capabilities(
    *,
    reasoning_provider: str,
    visual_provider: str,
    visual_mcp_provider: str | None = None,
) -> dict[str, dict[str, str]]:
    settings = get_settings()
    resolved = {
        "asr": _resolve_asr_capability(settings),
        "visual_understanding": _resolve_visual_capability(
            visual_provider=visual_provider,
            visual_mcp_provider=visual_mcp_provider,
        ),
        "ocr": _resolve_ocr_capability(settings),
        "hybrid_retrieval": _resolve_hybrid_retrieval_capability(settings),
        "reasoning": _resolve_reasoning_capability(settings, reasoning_provider=reasoning_provider),
        "verification": _resolve_verification_capability(settings),
    }
    return {slot: resolved[slot] for slot in CONTENT_UNDERSTANDING_CAPABILITY_SLOTS}


def _resolve_asr_capability(settings: Any) -> dict[str, str]:
    provider = _clean_text(getattr(settings, "transcription_provider", ""))
    if not provider or not bool(getattr(settings, "asr_evidence_enabled", False)):
        return _unavailable_capability()
    return _ready_capability(provider=provider, mode="native")


def _resolve_visual_capability(*, visual_provider: str, visual_mcp_provider: str | None) -> dict[str, str]:
    native_provider = _clean_text(visual_provider)
    if native_provider:
        return _ready_capability(provider=native_provider, mode="native_multimodal")

    mcp_provider = _clean_text(visual_mcp_provider)
    if mcp_provider:
        return _ready_capability(provider=mcp_provider, mode="visual_mcp")

    return _unavailable_capability()


def _resolve_ocr_capability(settings: Any) -> dict[str, str]:
    provider = _clean_text(getattr(settings, "ocr_provider", "paddleocr"))
    if not provider or not bool(getattr(settings, "ocr_enabled", False)):
        return _unavailable_capability()
    return _ready_capability(provider=provider, mode="native")


def _resolve_hybrid_retrieval_capability(settings: Any) -> dict[str, str]:
    provider = _clean_text(getattr(settings, "active_search_provider", "") or getattr(settings, "search_provider", ""))
    if not provider or not bool(getattr(settings, "entity_graph_enabled", False)):
        return _unavailable_capability()
    normalized_provider = "mixed" if provider == "auto" else provider
    return _ready_capability(provider=normalized_provider, mode="hybrid")


def _resolve_reasoning_capability(settings: Any, *, reasoning_provider: str) -> dict[str, str]:
    provider = _first_non_empty_text(
        reasoning_provider,
        getattr(settings, "active_reasoning_provider", ""),
        getattr(settings, "reasoning_provider", ""),
    )
    if not provider:
        return _unavailable_capability()
    return _ready_capability(provider=provider, mode="native")


def _resolve_verification_capability(settings: Any) -> dict[str, str]:
    provider = _clean_text(getattr(settings, "active_reasoning_provider", "") or getattr(settings, "reasoning_provider", ""))
    if not provider or not (
        bool(getattr(settings, "research_verifier_enabled", False)) or bool(getattr(settings, "fact_check_enabled", False))
    ):
        return _unavailable_capability()
    return _ready_capability(provider=provider, mode="verification")


def _ready_capability(*, provider: str, mode: str) -> dict[str, str]:
    return {"provider": provider, "mode": mode, "status": "ready"}


def _unavailable_capability() -> dict[str, str]:
    return {"provider": "", "mode": "unavailable", "status": "unavailable"}


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _first_non_empty_text(*values: object) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""
