from __future__ import annotations

from roughcut.config import (
    get_settings,
    has_distinct_backup_llm_route,
    llm_backup_route,
    normalize_transcription_settings,
    resolve_transcription_provider_plan as _resolve_plan,
)
from roughcut.providers.ocr.base import OCRProvider
from roughcut.providers.avatar.base import AvatarProvider
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse
from roughcut.providers.search.base import SearchProvider, SearchResult
from roughcut.providers.transcription.base import TranscriptionProvider
from roughcut.providers.voice.base import VoiceProvider

_TRANSCRIPTION_PROVIDER_CACHE: dict[tuple[str, str], TranscriptionProvider] = {}
_OCR_PROVIDER_CACHE: dict[str, OCRProvider] = {}
_AVATAR_PROVIDER_CACHE: dict[str, AvatarProvider] = {}
_VOICE_PROVIDER_CACHE: dict[str, VoiceProvider] = {}


class _FallbackReasoningProvider(ReasoningProvider):
    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        settings = get_settings()
        primary_provider_name = settings.active_reasoning_provider.lower()
        primary_model_name = settings.active_reasoning_model
        primary_provider = _build_reasoning_provider(primary_provider_name)
        try:
            return await primary_provider.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as primary_exc:
            with llm_backup_route(settings=settings):
                fallback_settings = get_settings()
                fallback_provider_name = fallback_settings.active_reasoning_provider.lower()
                if fallback_provider_name == primary_provider_name and (
                    fallback_settings.active_reasoning_model == primary_model_name
                ):
                    raise
                fallback_provider = _build_reasoning_provider(fallback_provider_name)
                try:
                    return await fallback_provider.complete(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                    )
                except Exception as fallback_exc:
                    raise RuntimeError(
                        "Reasoning provider fallback failed after primary route error: "
                        f"primary={type(primary_exc).__name__}: {primary_exc}; "
                        f"backup={type(fallback_exc).__name__}: {fallback_exc}"
                    ) from fallback_exc


class _FallbackSearchProvider(SearchProvider):
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        primary_provider_name = settings.active_reasoning_provider.lower()
        primary_model_name = settings.active_reasoning_model
        try:
            provider = _build_search_provider()
            return await provider.search(query, max_results=max_results)
        except Exception as primary_exc:
            with llm_backup_route(settings=settings):
                fallback_settings = get_settings()
                if fallback_settings.active_reasoning_provider.lower() == primary_provider_name and (
                    fallback_settings.active_reasoning_model == primary_model_name
                ):
                    raise
                try:
                    provider = _build_search_provider()
                    return await provider.search(query, max_results=max_results)
                except Exception as fallback_exc:
                    raise RuntimeError(
                        "Search provider fallback failed after primary route error: "
                        f"primary={type(primary_exc).__name__}: {primary_exc}; "
                        f"backup={type(fallback_exc).__name__}: {fallback_exc}"
                    ) from fallback_exc


def resolve_transcription_provider_plan(*, provider: str, model: str) -> list[tuple[str, str]]:
    return _resolve_plan(provider, model)


def get_transcription_provider(*, provider: str | None = None, model: str | None = None) -> TranscriptionProvider:
    settings = get_settings()
    provider, model = normalize_transcription_settings(
        provider or settings.transcription_provider,
        model or settings.transcription_model,
    )
    cache_key = (provider, model)
    cached = _TRANSCRIPTION_PROVIDER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if provider == "openai":
        from roughcut.providers.transcription.openai_whisper import OpenAIWhisperProvider

        instance = OpenAIWhisperProvider()
    elif provider == "funasr":
        from roughcut.providers.transcription.funasr_provider import FunASRProvider

        instance = FunASRProvider(model_name=model)
    elif provider == "faster_whisper":
        from roughcut.providers.transcription.local_whisper import LocalWhisperProvider

        instance = LocalWhisperProvider(model_size=model)
    elif provider == "qwen3_asr":
        from roughcut.providers.transcription.qwen_asr_http import QwenASRHTTPProvider

        instance = QwenASRHTTPProvider(model_name=model)
    else:
        raise ValueError(f"Unknown transcription provider: {provider}")
    _TRANSCRIPTION_PROVIDER_CACHE[cache_key] = instance
    return instance


def get_ocr_provider(*, provider: str | None = None) -> OCRProvider:
    settings = get_settings()
    provider_name = str(provider or getattr(settings, "ocr_provider", "paddleocr") or "paddleocr").strip().lower()
    cached = _OCR_PROVIDER_CACHE.get(provider_name)
    if cached is not None:
        return cached

    if provider_name == "paddleocr":
        from roughcut.providers.ocr.paddleocr_provider import PaddleOCRProvider

        instance = PaddleOCRProvider()
    else:
        raise ValueError(f"Unknown OCR provider: {provider_name}")

    _OCR_PROVIDER_CACHE[provider_name] = instance
    return instance


def get_reasoning_provider() -> ReasoningProvider:
    settings = get_settings()
    if has_distinct_backup_llm_route(settings=settings):
        return _FallbackReasoningProvider()
    return _build_reasoning_provider(settings.active_reasoning_provider.lower())


def _build_reasoning_provider(provider: str) -> ReasoningProvider:
    if provider == "openai":
        from roughcut.providers.reasoning.openai_reasoning import OpenAIReasoningProvider

        return OpenAIReasoningProvider()
    if provider == "anthropic":
        from roughcut.providers.reasoning.anthropic_reasoning import AnthropicReasoningProvider

        return AnthropicReasoningProvider()
    if provider == "minimax":
        from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider

        return MiniMaxReasoningProvider()
    if provider == "ollama":
        from roughcut.providers.reasoning.ollama_reasoning import OllamaReasoningProvider

        return OllamaReasoningProvider()
    raise ValueError(f"Unknown reasoning provider: {provider}")


def get_avatar_provider() -> AvatarProvider:
    settings = get_settings()
    provider = settings.avatar_provider.lower()
    cached = _AVATAR_PROVIDER_CACHE.get(provider)
    if cached is not None:
        return cached

    if provider == "heygem":
        from roughcut.providers.avatar.heygem import HeyGemAvatarProvider

        instance = HeyGemAvatarProvider()
    elif provider == "mock":
        raise ValueError("Mock avatar provider is disabled in runtime. Use HeyGem for real jobs.")
    else:
        raise ValueError(f"Unknown avatar provider: {provider}")

    _AVATAR_PROVIDER_CACHE[provider] = instance
    return instance


def get_voice_provider() -> VoiceProvider:
    settings = get_settings()
    provider = settings.voice_provider.lower()
    cached = _VOICE_PROVIDER_CACHE.get(provider)
    if cached is not None:
        return cached

    if provider == "indextts2":
        from roughcut.providers.voice.indextts2 import IndexTTS2VoiceProvider

        instance = IndexTTS2VoiceProvider()
    elif provider == "runninghub":
        from roughcut.providers.voice.runninghub import RunningHubVoiceProvider

        instance = RunningHubVoiceProvider()
    else:
        raise ValueError(f"Unknown voice provider: {provider}")

    _VOICE_PROVIDER_CACHE[provider] = instance
    return instance


def get_search_provider():
    settings = get_settings()
    if has_distinct_backup_llm_route(settings=settings):
        return _FallbackSearchProvider()
    return _build_search_provider()


def _build_search_provider():
    settings = get_settings()
    provider = settings.active_search_provider.lower()

    if provider == "disabled":
        raise RuntimeError("Search disabled for current task route")

    if provider == "auto":
        native_provider = settings.active_reasoning_provider.lower()
        try:
            if native_provider == "minimax" and (settings.minimax_coding_plan_api_key.strip() or settings.minimax_api_key.strip()):
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
            fallback = settings.active_search_fallback_provider.lower()
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
    if provider == "openai":
        from roughcut.providers.search.openai import OpenAISearchProvider

        return OpenAISearchProvider()
    if provider == "anthropic":
        from roughcut.providers.search.anthropic import AnthropicSearchProvider

        return AnthropicSearchProvider()
    if provider == "minimax":
        from roughcut.providers.search.minimax import MiniMaxSearchProvider

        return MiniMaxSearchProvider()
    if provider == "ollama":
        from roughcut.providers.search.ollama import OllamaSearchProvider

        return OllamaSearchProvider()
    if provider == "model":
        from roughcut.providers.search.model_search import ModelSearchProvider

        return ModelSearchProvider()
    if provider == "searxng":
        from roughcut.providers.search.searxng import SearXNGProvider

        return SearXNGProvider()
    raise ValueError(f"Unknown search provider: {provider}")
