from pathlib import Path

from roughcut.providers.minimax_compat import resolve_minimax_anthropic_base_url
from roughcut.providers.multimodal import _build_minimax_multimodal_content, _resolve_minimax_multimodal_model
from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities


def test_minimax_multimodal_content_uses_extracted_images_only() -> None:
    content = _build_minimax_multimodal_content(
        prompt="describe",
        image_paths=[Path("frame.jpg")],
        images_b64=["image-b64"],
    )

    assert content == [
        {"type": "text", "text": "describe"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": "image-b64"},
        },
    ]


def test_minimax_multimodal_model_is_forced_to_m3() -> None:
    assert _resolve_minimax_multimodal_model("MiniMax-M2.7") == "MiniMax-M3"
    assert _resolve_minimax_multimodal_model("MiniMax-M3") == "MiniMax-M3"


def test_minimax_anthropic_base_url_is_derived_from_legacy_openai_base_url() -> None:
    assert (
        resolve_minimax_anthropic_base_url(
            base_url="https://api.minimaxi.com/v1",
            api_host="https://api.minimaxi.com",
        )
        == "https://api.minimaxi.com/anthropic"
    )


def test_visual_capability_no_longer_falls_back_to_mcp(monkeypatch) -> None:
    from roughcut.review import content_understanding_capabilities as capabilities

    class DummySettings:
        transcription_provider = "local_http_asr"
        asr_evidence_enabled = True
        ocr_provider = "paddleocr"
        ocr_enabled = False
        active_search_provider = "minimax"
        search_provider = "minimax"
        entity_graph_enabled = False
        active_reasoning_provider = "minimax"
        reasoning_provider = "minimax"
        research_verifier_enabled = False
        fact_check_enabled = False

    monkeypatch.setattr(capabilities, "get_settings", lambda: DummySettings())

    resolved = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="",
        visual_mcp_provider="legacy_mcp",
    )

    assert resolved["visual_understanding"] == {
        "provider": "",
        "mode": "unavailable",
        "status": "unavailable",
    }
