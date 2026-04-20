from roughcut.creative.modes import (
    DEFAULT_LIVE_BATCH_ENHANCEMENT_MODES,
    resolve_live_batch_enhancement_modes,
)


def test_resolve_live_batch_enhancement_modes_uses_safe_defaults_without_translation():
    modes = resolve_live_batch_enhancement_modes([])

    assert modes == list(DEFAULT_LIVE_BATCH_ENHANCEMENT_MODES)
    assert "multilingual_translation" not in modes


def test_resolve_live_batch_enhancement_modes_respects_explicit_translation_request():
    modes = resolve_live_batch_enhancement_modes(
        ["auto_review", "multilingual_translation", "ai_effects", "multilingual_translation"]
    )

    assert modes == ["auto_review", "multilingual_translation", "ai_effects"]
