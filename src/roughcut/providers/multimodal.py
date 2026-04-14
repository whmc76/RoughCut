from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import time
from pathlib import Path
from threading import Lock

import httpx
import openai

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.openai_responses import (
    build_multimodal_input,
    build_reasoning_options,
    build_text_options,
    extract_response_output_text,
    extract_response_usage,
)
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.usage import record_usage_event


_VISION_MODEL_CACHE: str | None = None
_MULTIMODAL_CACHE_TTL_SECS = 15 * 60
_MULTIMODAL_MAX_CACHE_ENTRIES = 128
_MULTIMODAL_PROVIDER_DEFAULT_COOLDOWN_MS = {
    "minimax": 45_000,
    "openai": 15_000,
    "anthropic": 15_000,
}
_MULTIMODAL_PROVIDER_UNAVAILABLE_COOLDOWN_MS = {
    "ollama": 120_000,
    "minimax": 60_000,
    "openai": 30_000,
    "anthropic": 30_000,
}
_MULTIMODAL_PROVIDER_MAX_CONCURRENCY = {
    "minimax": 1,
}
_MULTIMODAL_RETRY_AFTER_RE = re.compile(
    r"(?:retry[_ -]?after|retry in|wait)\D*(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|sec|secs|seconds?)?",
    flags=re.IGNORECASE,
)
_MULTIMODAL_RESULT_CACHE: dict[str, tuple[float, str]] = {}
_MULTIMODAL_PROVIDER_COOLDOWNS: dict[str, tuple[float, str]] = {}
_MULTIMODAL_PROVIDER_SEMAPHORES: dict[str, tuple[int, asyncio.Semaphore]] = {}
_MULTIMODAL_STATE_LOCK = Lock()

logger = logging.getLogger(__name__)


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
    image_bytes = [path.read_bytes() for path in image_paths]
    cache_key = _build_multimodal_cache_key(
        prompt=prompt,
        image_bytes=image_bytes,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
        settings_signature="|".join(
            (
                str(settings.active_reasoning_provider or "").strip().lower(),
                str(settings.active_vision_model or settings.vision_model or "").strip(),
                str(settings.multimodal_fallback_provider or "").strip().lower(),
                str(settings.multimodal_fallback_model or "").strip(),
                str(settings.llm_mode or "").strip().lower(),
            )
        ),
    )
    cached = _get_cached_multimodal_result(cache_key)
    if cached is not None:
        return cached

    images_b64 = [base64.b64encode(blob).decode() for blob in image_bytes]

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
    preferred_error: Exception | None = None
    for provider, model in attempts:
        cooldown = _provider_cooldown_status(provider)
        if cooldown is not None:
            remaining_secs, detail = cooldown
            last_error = RuntimeError(
                f"Multimodal provider {provider} cooling down for {remaining_secs}s"
                + (f" ({detail})" if detail else "")
            )
            preferred_error = preferred_error or last_error
            continue
        try:
            content = await _complete_once(
                provider=provider,
                model=model,
                prompt=prompt,
                images_b64=images_b64,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            _store_cached_multimodal_result(cache_key, content)
            return content
        except Exception as exc:
            last_error = exc
            cooldown = _provider_cooldown_status(provider)
            if cooldown is not None:
                remaining_secs, detail = cooldown
                preferred_error = preferred_error or RuntimeError(
                    f"Multimodal provider {provider} cooling down for {remaining_secs}s"
                    + (f" ({detail})" if detail else "")
                )
                continue
            if _record_provider_transient_failure(provider, exc):
                preferred_error = preferred_error or exc
            elif _looks_like_fast_fallback_error(exc):
                preferred_error = preferred_error or exc

    final_error = preferred_error or last_error
    raise ValueError(f"Multimodal completion failed for providers {[name for name, _ in attempts]}: {final_error}")


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
    semaphore = _get_provider_semaphore(provider)

    if semaphore is None:
        try:
            return await _complete_once_unthrottled(
                provider=provider,
                model=model,
                prompt=prompt,
                images_b64=images_b64,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                settings=settings,
            )
        except Exception as exc:
            _record_provider_transient_failure(provider, exc)
            raise
    async with semaphore:
        try:
            return await _complete_once_unthrottled(
                provider=provider,
                model=model,
                prompt=prompt,
                images_b64=images_b64,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
                settings=settings,
            )
        except Exception as exc:
            _record_provider_transient_failure(provider, exc)
            raise


async def _complete_once_unthrottled(
    *,
    provider: str,
    model: str,
    prompt: str,
    images_b64: list[str],
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    settings,
) -> str:
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
            await _raise_for_multimodal_status(provider, response)
            data = response.json()
        _clear_provider_cooldown(provider)
        await record_usage_event(
            provider="ollama",
            model=model,
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            kind="multimodal",
        )
        return _finalize_text(data.get("message", {}).get("content", ""), json_mode=json_mode)

    if provider == "openai":
        client = openai.AsyncOpenAI(
            api_key=resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
            base_url=settings.openai_base_url.rstrip("/"),
        )
        data_urls = [f"data:image/jpeg;base64,{image}" for image in images_b64]
        payload: dict[str, object] = {
            "model": model,
            "input": build_multimodal_input(prompt, data_urls),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        text_options = build_text_options(json_mode=json_mode)
        if text_options:
            payload["text"] = text_options
        reasoning_options = build_reasoning_options(
            model,
            effort=str(getattr(settings, "active_reasoning_effort", "medium") or "medium"),
        )
        if reasoning_options:
            payload["reasoning"] = reasoning_options
        response = await client.responses.create(**payload)
        _clear_provider_cooldown(provider)
        await record_usage_event(
            provider=provider,
            model=str(response.model or model),
            usage=extract_response_usage(response),
            kind="multimodal",
        )
        return _finalize_text(extract_response_output_text(response), json_mode=json_mode)

    if provider == "minimax":
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
            await _raise_for_multimodal_status(provider, response)
            data = response.json()
        _clear_provider_cooldown(provider)
        usage_data = data.get("usage", {}) or {}
        await record_usage_event(
            provider=provider,
            model=str(data.get("model") or model),
            usage={
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
            },
            kind="multimodal",
        )
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
            await _raise_for_multimodal_status(provider, response)
            data = response.json()
        _clear_provider_cooldown(provider)
        parts = data.get("content", []) or []
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        usage_data = data.get("usage", {}) or {}
        await record_usage_event(
            provider="anthropic",
            model=str(data.get("model") or model),
            usage={
                "prompt_tokens": usage_data.get("input_tokens", 0),
                "completion_tokens": usage_data.get("output_tokens", 0),
            },
            kind="multimodal",
        )
        return _finalize_text(text, json_mode=json_mode)

    raise ValueError(f"Provider {provider} does not support multimodal completion")


async def _raise_for_multimodal_status(provider: str, response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    body_text = _safe_response_text(response)
    status = int(response.status_code)
    lower = body_text.lower()
    if status in {429, 503, 529} or "too many requests" in lower or "rate limit" in lower or "retry after" in lower:
        retry_after_ms = _resolve_retry_after_ms(response, body_text, provider=provider)
        _record_provider_cooldown(provider, retry_after_ms, body_text or response.reason_phrase)
    response.raise_for_status()


def _safe_response_text(response: httpx.Response) -> str:
    try:
        return response.text.strip()
    except Exception:
        return ""


def _resolve_retry_after_ms(response: httpx.Response, body_text: str, *, provider: str) -> int:
    header_ms = _parse_retry_after_ms(response.headers)
    if header_ms is not None:
        return header_ms
    body_ms = _extract_retry_after_ms(body_text)
    if body_ms is not None:
        return body_ms
    return _MULTIMODAL_PROVIDER_DEFAULT_COOLDOWN_MS.get(provider, 15_000)


def _parse_retry_after_ms(headers: httpx.Headers) -> int | None:
    for name in ("retry-after-ms", "x-retry-after-ms"):
        raw = headers.get(name)
        if raw:
            try:
                return max(0, int(float(raw)))
            except Exception:
                continue
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    if value >= 1000:
        return int(value)
    return int(value * 1000)


def _extract_retry_after_ms(text: str) -> int | None:
    match = _MULTIMODAL_RETRY_AFTER_RE.search(str(text or ""))
    if not match:
        return None
    value = float(match.group(1))
    unit = str(match.group(2) or "s").lower()
    if unit.startswith("ms"):
        return int(value)
    return int(value * 1000)


def _build_multimodal_cache_key(
    *,
    prompt: str,
    image_bytes: list[bytes],
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    settings_signature: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(str(prompt).encode("utf-8"))
    hasher.update(f"|{max_tokens}|{temperature:.4f}|{int(json_mode)}|".encode("ascii"))
    hasher.update(str(settings_signature).encode("utf-8"))
    for blob in image_bytes:
        digest = hashlib.sha256(blob).digest()
        hasher.update(digest)
    return hasher.hexdigest()


def _get_cached_multimodal_result(cache_key: str) -> str | None:
    now = time.monotonic()
    with _MULTIMODAL_STATE_LOCK:
        cached = _MULTIMODAL_RESULT_CACHE.get(cache_key)
        if cached is None:
            return None
        expires_at, content = cached
        if expires_at <= now:
            _MULTIMODAL_RESULT_CACHE.pop(cache_key, None)
            return None
        return content


def _store_cached_multimodal_result(cache_key: str, content: str) -> None:
    expires_at = time.monotonic() + _MULTIMODAL_CACHE_TTL_SECS
    with _MULTIMODAL_STATE_LOCK:
        _prune_multimodal_result_cache_locked(now=time.monotonic())
        _MULTIMODAL_RESULT_CACHE[cache_key] = (expires_at, content)
        if len(_MULTIMODAL_RESULT_CACHE) > _MULTIMODAL_MAX_CACHE_ENTRIES:
            oldest_key = min(_MULTIMODAL_RESULT_CACHE, key=lambda item: _MULTIMODAL_RESULT_CACHE[item][0])
            _MULTIMODAL_RESULT_CACHE.pop(oldest_key, None)


def _prune_multimodal_result_cache_locked(*, now: float) -> None:
    expired_keys = [key for key, (expires_at, _value) in _MULTIMODAL_RESULT_CACHE.items() if expires_at <= now]
    for key in expired_keys:
        _MULTIMODAL_RESULT_CACHE.pop(key, None)


def _provider_cooldown_status(provider: str) -> tuple[int, str] | None:
    now = time.monotonic()
    with _MULTIMODAL_STATE_LOCK:
        cooldown = _MULTIMODAL_PROVIDER_COOLDOWNS.get(provider)
        if cooldown is None:
            return None
        until, detail = cooldown
        if until <= now:
            _MULTIMODAL_PROVIDER_COOLDOWNS.pop(provider, None)
            return None
        return max(1, int(until - now)), detail


def _record_provider_cooldown(provider: str, retry_after_ms: int, detail: str) -> None:
    retry_after_ms = _cooldown_ms_for_provider_pressure(provider, retry_after_ms, detail)
    until = time.monotonic() + (retry_after_ms / 1000)
    detail_text = _normalize_cooldown_detail(detail)
    with _MULTIMODAL_STATE_LOCK:
        current = _MULTIMODAL_PROVIDER_COOLDOWNS.get(provider)
        if current is None or current[0] < until:
            _MULTIMODAL_PROVIDER_COOLDOWNS[provider] = (until, detail_text)
    logger.warning(
        "Multimodal provider %s cooling down for %.1fs after upstream pressure: %s",
        provider,
        retry_after_ms / 1000,
        detail_text,
    )


def _record_provider_transient_failure(provider: str, exc: Exception) -> bool:
    if isinstance(exc, httpx.ConnectError):
        _record_provider_cooldown(
            provider,
            _MULTIMODAL_PROVIDER_UNAVAILABLE_COOLDOWN_MS.get(provider, 30_000),
            f"{type(exc).__name__}: {exc}",
        )
        return True
    if isinstance(exc, httpx.TimeoutException):
        _record_provider_cooldown(
            provider,
            _MULTIMODAL_PROVIDER_UNAVAILABLE_COOLDOWN_MS.get(provider, 30_000),
            f"{type(exc).__name__}: {exc}",
        )
        return True
    return False


def _clear_provider_cooldown(provider: str) -> None:
    with _MULTIMODAL_STATE_LOCK:
        _MULTIMODAL_PROVIDER_COOLDOWNS.pop(provider, None)


def _normalize_cooldown_detail(detail: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(detail or "").strip())
    return cleaned[:240]


def _cooldown_ms_for_provider_pressure(provider: str, retry_after_ms: int, detail: str) -> int:
    retry_after_ms = max(retry_after_ms, _MULTIMODAL_PROVIDER_DEFAULT_COOLDOWN_MS.get(provider, 15_000))
    lower = str(detail or "").lower()
    if provider == "minimax" and any(
        token in lower
        for token in (
            "2062",
            "usage limit exceeded",
            "当前请求量较高",
            "更高并发",
            "higher concurrency",
            "token plan",
            "按量付费 api",
        )
    ):
        return max(retry_after_ms, 180_000)
    return retry_after_ms


def _looks_like_fast_fallback_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    message = str(exc or "").lower()
    return any(
        token in message
        for token in (
            "429",
            "too many requests",
            "rate limit",
            "timed out",
            "timeout",
            "cooling down",
            "cooldown",
            "connection refused",
            "connecterror",
            "all connection attempts failed",
        )
    )


def _get_provider_semaphore(provider: str) -> asyncio.Semaphore | None:
    limit = _MULTIMODAL_PROVIDER_MAX_CONCURRENCY.get(provider, 0)
    if limit <= 0:
        return None
    loop_id = id(asyncio.get_running_loop())
    with _MULTIMODAL_STATE_LOCK:
        cached = _MULTIMODAL_PROVIDER_SEMAPHORES.get(provider)
        if cached is None or cached[0] != loop_id:
            semaphore = asyncio.Semaphore(limit)
            _MULTIMODAL_PROVIDER_SEMAPHORES[provider] = (loop_id, semaphore)
            return semaphore
        return cached[1]


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
