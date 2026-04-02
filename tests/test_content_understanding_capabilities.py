from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from roughcut.config import CONTENT_UNDERSTANDING_CAPABILITY_SLOTS, Settings
from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities


def _make_settings(**overrides: object) -> SimpleNamespace:
    values = {
        "transcription_provider": "openai",
        "ocr_provider": "paddleocr",
        "search_provider": "auto",
        "search_fallback_provider": "searxng",
        "reasoning_provider": "minimax",
        "active_reasoning_provider": "minimax",
        "research_verifier_enabled": True,
        "fact_check_enabled": True,
        "asr_evidence_enabled": True,
        "entity_graph_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_settings_exposes_default_ocr_provider():
    assert Settings(_env_file=None).ocr_provider == "paddleocr"


def test_resolve_content_understanding_capabilities_covers_core_slots_and_is_json_serializable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "roughcut.review.content_understanding_capabilities.get_settings",
        lambda: _make_settings(),
    )

    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="minimax",
        visual_mcp_provider="mcp:minimax-vision",
    )

    assert tuple(capabilities.keys()) == CONTENT_UNDERSTANDING_CAPABILITY_SLOTS
    assert json.loads(json.dumps(capabilities, ensure_ascii=False)) == capabilities
    assert all(set(capabilities[slot]) == {"provider", "mode", "status"} for slot in CONTENT_UNDERSTANDING_CAPABILITY_SLOTS)


def test_resolve_content_understanding_capabilities_prefers_native_multimodal_over_visual_mcp(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "roughcut.review.content_understanding_capabilities.get_settings",
        lambda: _make_settings(),
    )

    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="minimax",
        visual_mcp_provider="mcp:minimax-vision",
    )

    assert capabilities["visual_understanding"] == {
        "provider": "minimax",
        "mode": "native_multimodal",
        "status": "ready",
    }


def test_resolve_content_understanding_capabilities_marks_visual_understanding_unavailable_when_no_route_exists(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "roughcut.review.content_understanding_capabilities.get_settings",
        lambda: _make_settings(),
    )

    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="",
        visual_mcp_provider="",
    )

    assert capabilities["visual_understanding"] == {
        "provider": "",
        "mode": "unavailable",
        "status": "unavailable",
    }


def test_resolve_content_understanding_capabilities_falls_back_from_blank_reasoning_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "roughcut.review.content_understanding_capabilities.get_settings",
        lambda: _make_settings(active_reasoning_provider="minimax", reasoning_provider="minimax"),
    )

    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="   ",
        visual_provider="",
        visual_mcp_provider="mcp:minimax-vision",
    )

    assert capabilities["reasoning"] == {
        "provider": "minimax",
        "mode": "native",
        "status": "ready",
    }


def test_resolve_content_understanding_capabilities_normalizes_auto_hybrid_retrieval_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "roughcut.review.content_understanding_capabilities.get_settings",
        lambda: _make_settings(search_provider="auto", active_search_provider="auto"),
    )

    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="minimax",
        visual_mcp_provider="",
    )

    assert capabilities["hybrid_retrieval"] == {
        "provider": "mixed",
        "mode": "hybrid",
        "status": "ready",
    }
