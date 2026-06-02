from types import SimpleNamespace

from roughcut.api.config import _build_model_route_entries
from roughcut.config import GLOBAL_MODEL_ROUTE_SETTINGS, PROFILE_BINDABLE_SETTINGS
from roughcut.config_profiles import _normalize_config_snapshot


def test_profile_bindable_settings_exclude_global_model_route_fields() -> None:
    overlap = set(PROFILE_BINDABLE_SETTINGS) & set(GLOBAL_MODEL_ROUTE_SETTINGS)

    assert overlap == set()
    assert "reasoning_provider" not in PROFILE_BINDABLE_SETTINGS
    assert "voice_provider" not in PROFILE_BINDABLE_SETTINGS
    assert "intelligent_copy_cover_image_backend" not in PROFILE_BINDABLE_SETTINGS
    assert "intelligent_copy_cover_image_backend" in GLOBAL_MODEL_ROUTE_SETTINGS


def test_profile_snapshot_strips_global_route_overrides() -> None:
    normalized = _normalize_config_snapshot(
        {
            "reasoning_provider": "openai",
            "reasoning_model": "gpt-5.5",
            "voice_provider": "indextts2",
            "intelligent_copy_cover_image_backend": "openai_images_api",
            "default_job_workflow_mode": "standard_edit",
            "avatar_presenter_id": "avatar/demo.mp4",
        }
    )

    assert "reasoning_provider" not in normalized
    assert "reasoning_model" not in normalized
    assert "voice_provider" not in normalized
    assert "intelligent_copy_cover_image_backend" not in normalized
    assert normalized["default_job_workflow_mode"] == "standard_edit"
    assert normalized["avatar_presenter_id"] == "avatar/demo.mp4"


def test_model_route_table_includes_cover_generation_route() -> None:
    settings = SimpleNamespace(
        transcription_provider="local_http_asr",
        transcription_model="qwen3-asr-1.7b-forced-aligner",
        transcription_dialect="mandarin",
        local_asr_display_name="Qwen3 ASR",
        local_asr_model_name="qwen3-asr-1.7b-forced-aligner",
        active_reasoning_provider="minimax",
        active_reasoning_model="MiniMax-M3",
        active_reasoning_effort="low",
        llm_mode="performance",
        llm_routing_mode="bundled",
        llm_backup_enabled=True,
        backup_reasoning_provider="minimax",
        backup_reasoning_model="MiniMax-M3",
        backup_reasoning_effort="low",
        backup_search_provider="searxng",
        hybrid_analysis_provider="minimax",
        hybrid_analysis_model="MiniMax-M3",
        hybrid_analysis_effort="low",
        hybrid_analysis_search_mode="entity_gated",
        hybrid_copy_provider="minimax",
        hybrid_copy_model="MiniMax-M3",
        hybrid_copy_effort="high",
        hybrid_copy_search_mode="follow_provider",
        search_provider="searxng",
        search_fallback_provider="searxng",
        model_search_helper="",
        multimodal_fallback_provider="minimax",
        multimodal_fallback_model="MiniMax-M3",
        voice_provider="runninghub",
        avatar_provider="heygem",
        ocr_provider="paddleocr",
        ocr_enabled=False,
        intelligent_copy_cover_image_generation_enabled=True,
        intelligent_copy_cover_image_backend="openai_images_api",
        intelligent_copy_cover_image_model="image2",
        intelligent_copy_cover_image_quality="high",
        intelligent_copy_cover_image_timeout_sec=120,
        intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
        intelligent_copy_cover_codex_runner_effort="low",
    )

    routes = {entry["key"]: entry for entry in _build_model_route_entries(settings)}

    assert "cover_image_generation" in routes
    assert routes["cover_image_generation"]["provider"] == "openai_images_api"
    assert routes["cover_image_generation"]["model"] == "image2"
    assert routes["cover_image_generation"]["enabled"] is True
    assert "quality=high" in routes["cover_image_generation"]["details"]


def test_model_route_table_describes_dreamina_cover_backend() -> None:
    settings = SimpleNamespace(
        transcription_provider="local_http_asr",
        transcription_model="qwen3-asr-1.7b-forced-aligner",
        transcription_dialect="mandarin",
        local_asr_display_name="Qwen3 ASR",
        local_asr_model_name="qwen3-asr-1.7b-forced-aligner",
        active_reasoning_provider="minimax",
        active_reasoning_model="MiniMax-M3",
        active_reasoning_effort="low",
        llm_mode="performance",
        llm_routing_mode="bundled",
        llm_backup_enabled=True,
        backup_reasoning_provider="minimax",
        backup_reasoning_model="MiniMax-M3",
        backup_reasoning_effort="low",
        backup_search_provider="searxng",
        hybrid_analysis_provider="minimax",
        hybrid_analysis_model="MiniMax-M3",
        hybrid_analysis_effort="low",
        hybrid_analysis_search_mode="entity_gated",
        hybrid_copy_provider="minimax",
        hybrid_copy_model="MiniMax-M3",
        hybrid_copy_effort="high",
        hybrid_copy_search_mode="follow_provider",
        search_provider="searxng",
        search_fallback_provider="searxng",
        model_search_helper="",
        multimodal_fallback_provider="minimax",
        multimodal_fallback_model="MiniMax-M3",
        voice_provider="runninghub",
        avatar_provider="heygem",
        ocr_provider="paddleocr",
        ocr_enabled=False,
        intelligent_copy_cover_image_generation_enabled=True,
        intelligent_copy_cover_image_backend="dreamina_web",
        intelligent_copy_cover_image_model="",
        intelligent_copy_cover_image_quality="2k",
        intelligent_copy_cover_image_timeout_sec=180,
        intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
        intelligent_copy_cover_codex_runner_effort="low",
        intelligent_copy_cover_dreamina_command="node",
    )

    routes = {entry["key"]: entry for entry in _build_model_route_entries(settings)}

    assert routes["cover_image_generation"]["provider"] == "dreamina_web"
    assert routes["cover_image_generation"]["model"] == "auto(4.5_text/5.0_reference)"
    assert "routing=text->http_replay,reference->cdp_page" in routes["cover_image_generation"]["details"]
