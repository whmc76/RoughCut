from __future__ import annotations

import base64
import re
from pathlib import Path

import httpx

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.reasoning.base import extract_json_text


_VISION_MODEL_CACHE: str | None = None


def _strip_reasoning_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def complete_with_images(
    prompt: str,
    image_paths: list[Path],
    *,
    max_tokens: int = 800,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    settings = get_settings()
    images_b64 = [base64.b64encode(path.read_bytes()).decode() for path in image_paths]

    primary_provider = settings.active_reasoning_provider.lower()
    attempts: list[tuple[str, str]] = [
        (
            primary_provider,
            settings.active_vision_model or await _resolve_vision_model(provider=primary_provider),
        )
    ]

    fallback_provider = settings.multimodal_fallback_provider.lower().strip()
    if settings.llm_mode != "local" and fallback_provider and fallback_provider != attempts[0][0]:
        try:
            fallback_model = settings.multimodal_fallback_model or await _resolve_vision_model(provider=fallback_provider)
            attempts.append((fallback_provider, fallback_model))
        except Exception:
            pass

    last_error: Exception | None = None
    for provider, model in attempts:
        try:
            return await _complete_once(
                provider=provider,
                model=model,
                prompt=prompt,
                images_b64=images_b64,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Multimodal completion failed for providers {[name for name, _ in attempts]}: {last_error}")


async def _complete_once(
    *,
    provider: str,
    model: str,
    prompt: str,
    images_b64: list[str],
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> str:
    settings = get_settings()

    if provider == "ollama":
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": images_b64}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return _finalize_text(data.get("message", {}).get("content", ""), json_mode=json_mode)

    if provider in {"openai", "minimax"}:
        base_url, token = _resolve_openai_compatible(provider)
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image in images_b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}})
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return _finalize_text(data["choices"][0]["message"]["content"], json_mode=json_mode)

    if provider == "anthropic":
        token = resolve_credential(
            mode=settings.anthropic_auth_mode,
            direct_value=settings.anthropic_api_key,
            helper_command=settings.anthropic_api_key_helper,
            provider_name="Anthropic",
        )
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image in images_b64:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": image},
                }
            )
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.anthropic_base_url.rstrip('/')}/v1/messages",
                headers={
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01",
                    "x-api-key": token,
                    "authorization": f"Bearer {token}",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        parts = data.get("content", []) or []
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        return _finalize_text(text, json_mode=json_mode)

    raise ValueError(f"Provider {provider} does not support multimodal completion")


def _resolve_openai_compatible(provider: str) -> tuple[str, str]:
    settings = get_settings()
    if provider == "openai":
        return (
            settings.openai_base_url.rstrip("/"),
            resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
        )
    if provider == "minimax":
        token = settings.minimax_api_key.strip()
        if not token:
            raise ValueError("MiniMax API credential is not configured")
        return settings.minimax_base_url.rstrip("/"), token
    raise ValueError(f"Unsupported OpenAI-compatible provider: {provider}")


def _finalize_text(text: str, *, json_mode: bool) -> str:
    cleaned = _strip_reasoning_tags(str(text).strip())
    if json_mode:
        return extract_json_text(cleaned)
    return cleaned


async def _resolve_vision_model(*, provider: str | None = None) -> str:
    global _VISION_MODEL_CACHE
    if provider is None and _VISION_MODEL_CACHE:
        return _VISION_MODEL_CACHE

    settings = get_settings()
    if settings.vision_model:
        if provider is None:
            _VISION_MODEL_CACHE = settings.vision_model
        return settings.vision_model

    active_provider = (provider or settings.active_reasoning_provider).lower()
    if active_provider != "ollama":
        if provider is None:
            _VISION_MODEL_CACHE = settings.active_vision_model
            return _VISION_MODEL_CACHE
        return settings.active_vision_model

    preferred_keywords = (
        "glm-4.7-flash",
        "glm4",
        "vision",
        "vl",
        "llava",
        "moondream",
        "qwen2.5vl",
        "minicpm-v",
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            data = response.json()
        model_names = [item.get("name", "") for item in data.get("models", [])]
        for keyword in preferred_keywords:
            for model_name in model_names:
                if keyword in model_name.lower():
                    if provider is None:
                        _VISION_MODEL_CACHE = model_name
                        return _VISION_MODEL_CACHE
                    return model_name
    except Exception:
        pass

    if provider is None and settings.active_reasoning_provider.lower() == "ollama":
        _VISION_MODEL_CACHE = settings.active_vision_model
        return _VISION_MODEL_CACHE
    if provider == "ollama" and settings.active_reasoning_provider.lower() == "ollama":
        return settings.active_vision_model
    raise ValueError("No Ollama vision model found; set VISION_MODEL or MULTIMODAL_FALLBACK_MODEL")
