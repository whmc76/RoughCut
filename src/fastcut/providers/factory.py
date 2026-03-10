from __future__ import annotations

from fastcut.config import get_settings
from fastcut.providers.reasoning.base import ReasoningProvider
from fastcut.providers.transcription.base import TranscriptionProvider


def get_transcription_provider() -> TranscriptionProvider:
    settings = get_settings()
    provider = settings.transcription_provider.lower()

    if provider == "openai":
        from fastcut.providers.transcription.openai_whisper import OpenAIWhisperProvider

        return OpenAIWhisperProvider()
    elif provider == "local_whisper":
        from fastcut.providers.transcription.local_whisper import LocalWhisperProvider

        return LocalWhisperProvider()
    else:
        raise ValueError(f"Unknown transcription provider: {provider}")


def get_reasoning_provider() -> ReasoningProvider:
    settings = get_settings()
    provider = settings.reasoning_provider.lower()

    if provider == "openai":
        from fastcut.providers.reasoning.openai_reasoning import OpenAIReasoningProvider

        return OpenAIReasoningProvider()
    elif provider == "anthropic":
        from fastcut.providers.reasoning.anthropic_reasoning import AnthropicReasoningProvider

        return AnthropicReasoningProvider()
    elif provider == "ollama":
        from fastcut.providers.reasoning.ollama_reasoning import OllamaReasoningProvider

        return OllamaReasoningProvider()
    else:
        raise ValueError(f"Unknown reasoning provider: {provider}")


def get_search_provider():
    settings = get_settings()
    provider = settings.search_provider.lower()

    if provider == "searxng":
        from fastcut.providers.search.searxng import SearXNGProvider

        return SearXNGProvider()
    else:
        raise ValueError(f"Unknown search provider: {provider}")
