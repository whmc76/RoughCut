from __future__ import annotations

from roughcut.config import get_settings
from roughcut.providers.reasoning.base import ReasoningProvider
from roughcut.providers.transcription.base import TranscriptionProvider

_TRANSCRIPTION_PROVIDER_CACHE: dict[tuple[str, str], TranscriptionProvider] = {}


def get_transcription_provider() -> TranscriptionProvider:
    settings = get_settings()
    provider = settings.transcription_provider.lower()
    model = settings.transcription_model
    cache_key = (provider, model)
    cached = _TRANSCRIPTION_PROVIDER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if provider == "openai":
        from roughcut.providers.transcription.openai_whisper import OpenAIWhisperProvider

        instance = OpenAIWhisperProvider()
    elif provider == "local_whisper":
        from roughcut.providers.transcription.local_whisper import LocalWhisperProvider

        instance = LocalWhisperProvider(model_size=model)
    else:
        raise ValueError(f"Unknown transcription provider: {provider}")
    _TRANSCRIPTION_PROVIDER_CACHE[cache_key] = instance
    return instance


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
        native_provider = settings.active_reasoning_provider.lower()
        try:
            if native_provider == "minimax" and settings.minimax_api_key.strip():
                from roughcut.providers.search.minimax import MiniMaxSearchProvider

                return MiniMaxSearchProvider()
            if native_provider == "openai":
                from roughcut.providers.search.openai import OpenAISearchProvider

                return OpenAISearchProvider()
            if native_provider == "anthropic":
                from roughcut.providers.search.anthropic import AnthropicSearchProvider

                return AnthropicSearchProvider()
            if native_provider == "ollama" and settings.ollama_api_key.strip():
                from roughcut.providers.search.ollama import OllamaSearchProvider

                return OllamaSearchProvider()
        except Exception:
            pass

        if settings.llm_mode != "local":
            try:
                from roughcut.providers.search.model_search import ModelSearchProvider

                return ModelSearchProvider()
            except Exception:
                pass

        try:
            fallback = settings.search_fallback_provider.lower()
            if fallback == "openai":
                from roughcut.providers.search.openai import OpenAISearchProvider

                return OpenAISearchProvider()
            if fallback == "anthropic":
                from roughcut.providers.search.anthropic import AnthropicSearchProvider

                return AnthropicSearchProvider()
            if fallback == "minimax":
                from roughcut.providers.search.minimax import MiniMaxSearchProvider

                return MiniMaxSearchProvider()
            if fallback == "ollama":
                from roughcut.providers.search.ollama import OllamaSearchProvider

                return OllamaSearchProvider()
            if fallback == "searxng":
                from roughcut.providers.search.searxng import SearXNGProvider

                return SearXNGProvider()
            if fallback == "model":
                from roughcut.providers.search.model_search import ModelSearchProvider

                return ModelSearchProvider()
            raise ValueError(f"Unknown search fallback provider: {fallback}")
        except Exception:
            if settings.llm_mode != "local":
                try:
                    from roughcut.providers.search.model_search import ModelSearchProvider

                    return ModelSearchProvider()
                except Exception:
                    pass
            raise
    elif provider == "openai":
        from roughcut.providers.search.openai import OpenAISearchProvider

        return OpenAISearchProvider()
    elif provider == "anthropic":
        from roughcut.providers.search.anthropic import AnthropicSearchProvider

        return AnthropicSearchProvider()
    elif provider == "minimax":
        from roughcut.providers.search.minimax import MiniMaxSearchProvider

        return MiniMaxSearchProvider()
    elif provider == "ollama":
        from roughcut.providers.search.ollama import OllamaSearchProvider

        return OllamaSearchProvider()
    elif provider == "model":
        from roughcut.providers.search.model_search import ModelSearchProvider

        return ModelSearchProvider()
    elif provider == "searxng":
        from roughcut.providers.search.searxng import SearXNGProvider

        return SearXNGProvider()
    else:
        raise ValueError(f"Unknown search provider: {provider}")
