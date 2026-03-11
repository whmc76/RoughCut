from __future__ import annotations

from roughcut.config import get_settings
from roughcut.providers.reasoning.base import ReasoningProvider
from roughcut.providers.transcription.base import TranscriptionProvider


def get_transcription_provider() -> TranscriptionProvider:
    settings = get_settings()
    provider = settings.transcription_provider.lower()

    if provider == "openai":
        from roughcut.providers.transcription.openai_whisper import OpenAIWhisperProvider

        return OpenAIWhisperProvider()
    elif provider == "local_whisper":
        from roughcut.providers.transcription.local_whisper import LocalWhisperProvider

        return LocalWhisperProvider(model_size=settings.transcription_model)
    else:
        raise ValueError(f"Unknown transcription provider: {provider}")


def get_reasoning_provider() -> ReasoningProvider:
    settings = get_settings()
    provider = settings.active_reasoning_provider.lower()

    if provider == "openai":
        from roughcut.providers.reasoning.openai_reasoning import OpenAIReasoningProvider

        return OpenAIReasoningProvider()
    elif provider == "anthropic":
        from roughcut.providers.reasoning.anthropic_reasoning import AnthropicReasoningProvider

        return AnthropicReasoningProvider()
    elif provider == "minimax":
        from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider

        return MiniMaxReasoningProvider()
    elif provider == "ollama":
        from roughcut.providers.reasoning.ollama_reasoning import OllamaReasoningProvider

        return OllamaReasoningProvider()
    else:
        raise ValueError(f"Unknown reasoning provider: {provider}")


def get_search_provider():
    settings = get_settings()
    provider = settings.active_search_provider.lower()

    if provider == "auto":
        try:
            from roughcut.providers.search.model_search import ModelSearchProvider

            return ModelSearchProvider()
        except Exception:
            fallback = settings.search_fallback_provider.lower()
            if fallback == "searxng":
                from roughcut.providers.search.searxng import SearXNGProvider

                return SearXNGProvider()
            raise ValueError(f"Unknown search fallback provider: {fallback}")
    elif provider == "model":
        from roughcut.providers.search.model_search import ModelSearchProvider

        return ModelSearchProvider()
    elif provider == "searxng":
        from roughcut.providers.search.searxng import SearXNGProvider

        return SearXNGProvider()
    else:
        raise ValueError(f"Unknown search provider: {provider}")
