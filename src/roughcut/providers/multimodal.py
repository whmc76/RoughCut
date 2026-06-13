from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from threading import Lock

import httpx
import openai

from roughcut.config import DEFAULT_MINIMAX_REASONING_MODEL, DEFAULT_ZHIPU_VISION_MODEL, get_settings, uses_codex_auth_helper
from roughcut.host.codex_proxy import resolve_codex_proxy_token, resolve_codex_proxy_url
from roughcut.providers.minimax_compat import resolve_minimax_anthropic_base_url
from roughcut.providers.auth import resolve_credential
from roughcut.providers.openai_responses import (
    build_multimodal_input,
    build_reasoning_options,
    build_text_options,
    extract_response_output_text,
    extract_response_usage,
)
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.providers.zhipu_compat import normalize_zhipu_base_url
from roughcut.providers.zhipu_http import build_zhipu_headers, build_zhipu_request_context, post_zhipu_json
from roughcut.usage import record_usage_event


_VISION_MODEL_CACHE: str | None = None
_MULTIMODAL_CACHE_TTL_SECS = 15 * 60
_MULTIMODAL_MAX_CACHE_ENTRIES = 128
_DEFAULT_OPENAI_MULTIMODAL_MODEL = "gpt-5.5"
_MULTIMODAL_PROVIDER_DEFAULT_COOLDOWN_MS = {
    "minimax": 45_000,
    "zhipu": 30_000,
    "openai": 15_000,
    "anthropic": 15_000,
}
_MULTIMODAL_PROVIDER_UNAVAILABLE_COOLDOWN_MS = {
    "ollama": 120_000,
    "minimax": 60_000,
    "zhipu": 45_000,
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


def _active_multimodal_fallback_provider(settings) -> str:
    return str(
        getattr(
            settings,
            "active_multimodal_fallback_provider",
            getattr(settings, "multimodal_fallback_provider", ""),
        )
        or ""
    ).strip().lower()


def _active_multimodal_fallback_model(settings) -> str:
    return str(
        getattr(
            settings,
            "active_multimodal_fallback_model",
            getattr(settings, "multimodal_fallback_model", ""),
        )
        or ""
    ).strip()


def _openai_direct_api_unavailable(settings) -> bool:
    if not uses_codex_auth_helper(settings):
        return False
    if str(getattr(settings, "openai_api_key", "") or "").strip():
        return False
    return not str(getattr(settings, "openai_api_key_helper", "") or "").strip()


def _is_provider_compatible_multimodal_model(provider: str, model: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if not normalized_model:
        return False
    if normalized_provider == "openai":
        return normalized_model.startswith(("gpt-", "o1", "o3", "o4")) or "codex" in normalized_model
    if normalized_provider == "minimax":
        return normalized_model.startswith("minimax") or normalized_model.startswith("abab")
    if normalized_provider == "zhipu":
        return normalized_model.startswith("glm-") and "v" in normalized_model
    if normalized_provider == "anthropic":
        return normalized_model.startswith("claude")
    return True


def _default_multimodal_model_for_provider(provider: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "openai":
        return _DEFAULT_OPENAI_MULTIMODAL_MODEL
    if normalized_provider == "minimax":
        return DEFAULT_MINIMAX_REASONING_MODEL
    if normalized_provider == "zhipu":
        return DEFAULT_ZHIPU_VISION_MODEL
    return ""


def _has_minimax_multimodal_credentials(settings) -> bool:
    return bool(str(getattr(settings, "minimax_api_key", "") or "").strip())


def _has_zhipu_multimodal_credentials(settings) -> bool:
    auth_mode = str(getattr(settings, "zhipu_auth_mode", "") or "api_key").strip().lower()
    if auth_mode == "helper":
        return bool(str(getattr(settings, "zhipu_api_key_helper", "") or "").strip())
    return bool(str(getattr(settings, "zhipu_api_key", "") or "").strip())


def _can_attempt_multimodal_provider(provider: str, settings) -> bool:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return not _openai_direct_api_unavailable(settings)
    if normalized == "minimax":
        return _has_minimax_multimodal_credentials(settings)
    if normalized == "zhipu":
        return _has_zhipu_multimodal_credentials(settings)
    return True


async def complete_with_images(
    prompt: str,
    image_paths: list[Path],
    *,
    max_tokens: int = 800,
    temperature: float = 0.2,
    json_mode: bool = False,
    preferred_provider: str | None = None,
    preferred_model: str | None = None,
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
                    _active_multimodal_fallback_provider(settings),
                    _active_multimodal_fallback_model(settings),
                    str(preferred_provider or "").strip().lower(),
                    str(preferred_model or "").strip(),
                    str(settings.llm_mode or "").strip().lower(),
                )
            ),
    )
    cached = _get_cached_multimodal_result(cache_key)
    if cached is not None:
        return cached

    images_b64 = [base64.b64encode(blob).decode() for blob in image_bytes]

    normalized_preferred_provider = str(preferred_provider or "").strip().lower()
    normalized_preferred_model = str(preferred_model or "").strip()
    primary_provider = settings.active_reasoning_provider.lower()
    attempts: list[tuple[str, str]] = []
    preferred_error: Exception | None = None
    if normalized_preferred_provider:
        if _can_attempt_multimodal_provider(normalized_preferred_provider, settings):
            preferred_attempt_model = normalized_preferred_model or await _resolve_vision_model(provider=normalized_preferred_provider)
            attempts.append((normalized_preferred_provider, preferred_attempt_model))
        else:
            preferred_error = RuntimeError(
                f"Multimodal provider {normalized_preferred_provider} is unavailable with the current credential mode"
            )
    elif _can_attempt_multimodal_provider(primary_provider, settings):
        attempts.append(
            (
                primary_provider,
                settings.active_vision_model or await _resolve_vision_model(provider=primary_provider),
            )
        )
    else:
        preferred_error = RuntimeError(
            f"Multimodal provider {primary_provider} is unavailable with the current credential mode"
        )

    fallback_provider = _active_multimodal_fallback_provider(settings)
    effective_primary_provider = normalized_preferred_provider or primary_provider
    if settings.llm_mode != "local" and fallback_provider and fallback_provider != effective_primary_provider:
        try:
            if _can_attempt_multimodal_provider(fallback_provider, settings):
                fallback_model = _active_multimodal_fallback_model(settings) or await _resolve_vision_model(provider=fallback_provider)
                attempts.append((fallback_provider, fallback_model))
        except Exception:
            pass
    if not attempts and _has_minimax_multimodal_credentials(settings):
        minimax_model = (
            _active_multimodal_fallback_model(settings)
            if fallback_provider == "minimax"
            else DEFAULT_MINIMAX_REASONING_MODEL
        )
        attempts.append(("minimax", minimax_model or DEFAULT_MINIMAX_REASONING_MODEL))
    if not attempts and _has_zhipu_multimodal_credentials(settings):
        zhipu_model = (
            _active_multimodal_fallback_model(settings)
            if fallback_provider == "zhipu"
            else DEFAULT_ZHIPU_VISION_MODEL
        )
        attempts.append(("zhipu", zhipu_model or DEFAULT_ZHIPU_VISION_MODEL))
    configured_attempt_providers = {provider for provider, _model in attempts}
    if len(configured_attempt_providers) <= 1:
        for alternate_provider in ("openai", "anthropic"):
            if alternate_provider in configured_attempt_providers:
                continue
            if not _can_attempt_multimodal_provider(alternate_provider, settings):
                continue
            try:
                alternate_model = await _resolve_vision_model(provider=alternate_provider)
            except Exception:
                continue
            attempts.append((alternate_provider, alternate_model))
            configured_attempt_providers.add(alternate_provider)
            break

    last_error: Exception | None = None
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
                image_paths=image_paths,
                images_b64=images_b64,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            content = _normalize_json_mode_multimodal_content(content, json_mode=json_mode)
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

    final_error = last_error or preferred_error
    raise ValueError(f"Multimodal completion failed for providers {[name for name, _ in attempts]}: {final_error}")


def _normalize_json_mode_multimodal_content(content: str, *, json_mode: bool) -> str:
    if not json_mode:
        return content
    try:
        payload = json.loads(str(content or ""))
    except Exception:
        return content
    if set(payload.keys()) != {"text"}:
        return content
    shell_text = _strip_reasoning_tags(str(payload.get("text") or "").strip())
    if not shell_text:
        raise ValueError("Multimodal json_mode returned an empty text shell")
    return extract_json_text(shell_text)


async def _complete_once(
    *,
    provider: str,
    model: str,
    prompt: str,
    image_paths: list[Path],
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
                image_paths=image_paths,
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
                image_paths=image_paths,
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
    image_paths: list[Path],
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
        if uses_codex_auth_helper(settings) and not str(getattr(settings, "openai_api_key", "") or "").strip():
            return await _complete_openai_via_codex_bridge(
                model=model,
                prompt=prompt,
                media_paths=image_paths,
                json_mode=json_mode,
                settings=settings,
            )
        client = openai.AsyncOpenAI(
            api_key=resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
            base_url=settings.openai_base_url.rstrip("/"),
        )
        data_urls = [
            f"data:{_guess_media_type(path)};base64,{image}"
            for path, image in zip(image_paths, images_b64, strict=False)
        ]
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
            effort=str(getattr(settings, "active_reasoning_effort", "low") or "low"),
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
        return await _complete_minimax_anthropic_multimodal(
            prompt=prompt,
            image_paths=image_paths,
            images_b64=images_b64,
            json_mode=json_mode,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            settings=settings,
        )

    if provider == "zhipu":
        return await _complete_zhipu_multimodal(
            prompt=prompt,
            image_paths=image_paths,
            images_b64=images_b64,
            json_mode=json_mode,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            settings=settings,
        )

    if provider == "anthropic":
        token = resolve_credential(
            mode=settings.anthropic_auth_mode,
            direct_value=settings.anthropic_api_key,
            helper_command=settings.anthropic_api_key_helper,
            provider_name="Anthropic",
        )
        content: list[dict] = [{"type": "text", "text": prompt}]
        for path, image in zip(image_paths, images_b64, strict=False):
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": _guess_media_type(path), "data": image},
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


async def _complete_openai_via_codex_bridge(
    *,
    model: str,
    prompt: str,
    media_paths: list[Path],
    json_mode: bool,
    settings,
) -> str:
    del settings
    url = _resolve_codex_bridge_exec_url()
    if not url:
        raise RuntimeError("Codex host bridge is not configured for OpenAI multimodal completion")

    timeout = max(30, int(os.getenv("ROUGHCUT_MULTIMODAL_CODEX_TIMEOUT_SEC", "300") or "300"))
    staged_media_context = _stage_codex_bridge_media_paths(media_paths)
    with staged_media_context as staged_media_paths:
        payload: dict[str, object] = {
            "repo_root": str(Path.cwd()),
            "prompt": _build_codex_multimodal_prompt(prompt, json_mode=json_mode),
            "model": model,
            "timeout_sec": timeout,
            "images": [str(path) for path in staged_media_paths],
        }
        if json_mode:
            payload["output_schema"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "payload_json": {"type": "string"},
                },
                "required": ["payload_json"],
            }

        headers = {"Content-Type": "application/json"}
        token = resolve_codex_proxy_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

    _clear_provider_cooldown("openai")
    raw_text = str(data.get("stdout") or data.get("excerpt") or "").strip()
    if json_mode:
        try:
            raw_text = str(json.loads(raw_text).get("payload_json") or "").strip()
        except Exception:
            pass
    await record_usage_event(
        provider="openai",
        model=model,
        usage={"prompt_tokens": 0, "completion_tokens": 0},
        kind="multimodal",
    )
    return _finalize_text(raw_text, json_mode=json_mode)


def _stage_codex_bridge_media_paths(media_paths: list[Path]):
    if not any(_should_stage_codex_bridge_media_path(path) for path in media_paths):
        return _passthrough_media_paths_context(media_paths)
    tempdir = tempfile.TemporaryDirectory(prefix="roughcut-codex-mm-")
    staged_paths: list[Path] = []
    temp_root = Path(tempdir.name)
    for index, original in enumerate(media_paths, start=1):
        suffix = original.suffix or ".bin"
        staged = temp_root / f"media_{index:02d}{suffix}"
        shutil.copyfile(original, staged)
        staged_paths.append(staged)
    return _temporary_media_paths_context(tempdir, staged_paths)


def _should_stage_codex_bridge_media_path(path: Path) -> bool:
    normalized = str(path or "")
    return normalized.startswith("\\\\")


class _passthrough_media_paths_context:
    def __init__(self, media_paths: list[Path]):
        self._media_paths = list(media_paths)

    def __enter__(self) -> list[Path]:
        return list(self._media_paths)

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _temporary_media_paths_context:
    def __init__(self, tempdir: tempfile.TemporaryDirectory, staged_paths: list[Path]):
        self._tempdir = tempdir
        self._staged_paths = list(staged_paths)

    def __enter__(self) -> list[Path]:
        return list(self._staged_paths)

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._tempdir.cleanup()
        return False


async def _complete_minimax_anthropic_multimodal(
    *,
    prompt: str,
    image_paths: list[Path],
    images_b64: list[str],
    json_mode: bool,
    model: str,
    max_tokens: int,
    temperature: float,
    settings,
) -> str:
    token = str(getattr(settings, "minimax_api_key", "") or "").strip()
    if not token:
        raise ValueError("MiniMax API key is not configured")
    if not images_b64:
        return _finalize_text("", json_mode=json_mode)

    base_url = resolve_minimax_anthropic_base_url(
        base_url=str(getattr(settings, "minimax_base_url", "") or ""),
        api_host=str(getattr(settings, "minimax_api_host", "") or ""),
    )
    payload = {
        "model": _resolve_minimax_multimodal_model(model),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {
                "role": "user",
                "content": _build_minimax_multimodal_content(
                    prompt=prompt,
                    image_paths=image_paths,
                    images_b64=images_b64,
                ),
            }
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": token,
        "authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{base_url}/v1/messages",
            headers=headers,
            json=payload,
        )
        await _raise_for_multimodal_status("minimax", response)
        data = response.json()

    _clear_provider_cooldown("minimax")
    parts = data.get("content", []) or []
    text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
    usage_data = data.get("usage", {}) or {}
    await record_usage_event(
        provider="minimax",
        model=str(data.get("model") or _resolve_minimax_multimodal_model(model)),
        usage={
            "prompt_tokens": int(usage_data.get("input_tokens", 0) or 0),
            "completion_tokens": int(usage_data.get("output_tokens", 0) or 0),
        },
        kind="multimodal",
    )
    return _finalize_text(text, json_mode=json_mode)


async def _complete_zhipu_multimodal(
    *,
    prompt: str,
    image_paths: list[Path],
    images_b64: list[str],
    json_mode: bool,
    model: str,
    max_tokens: int,
    temperature: float,
    settings,
) -> str:
    token = resolve_credential(
        mode=settings.zhipu_auth_mode,
        direct_value=settings.zhipu_api_key,
        helper_command=settings.zhipu_api_key_helper,
        provider_name="Zhipu",
    )
    payload: dict[str, object] = {
        "model": model or DEFAULT_ZHIPU_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": _build_zhipu_multimodal_content(
                    prompt=prompt,
                    image_paths=image_paths,
                    images_b64=images_b64,
                ),
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        **build_zhipu_request_context(),
    }
    effort = str(getattr(settings, "active_reasoning_effort", "low") or "low").strip().lower()
    thinking_efforts = {"medium", "high", "xhigh", "max", "ultracode"}
    enable_thinking = (not json_mode) and effort in thinking_efforts and int(max_tokens) >= 256
    payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    if json_mode:
        payload["messages"] = [
            {
                "role": "user",
                "content": _build_zhipu_multimodal_content(
                    prompt=f"{prompt}\n\nRespond with valid JSON only.",
                    image_paths=image_paths,
                    images_b64=images_b64,
                ),
            }
        ]
    data = await post_zhipu_json(
        url=f"{normalize_zhipu_base_url(settings.zhipu_base_url)}/chat/completions",
        headers=build_zhipu_headers(token),
        json_payload=payload,
        timeout_sec=120,
        max_attempts=3,
    )

    _clear_provider_cooldown("zhipu")
    choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
    message = choice.get("message") or {}
    content = _extract_zhipu_message_content(message)
    if not content and enable_thinking and str(message.get("reasoning_content") or "").strip():
        payload["thinking"] = {"type": "disabled"}
        data = await post_zhipu_json(
            url=f"{normalize_zhipu_base_url(settings.zhipu_base_url)}/chat/completions",
            headers=build_zhipu_headers(token),
            json_payload=payload,
            timeout_sec=120,
            max_attempts=2,
        )
        choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
        message = choice.get("message") or {}
        content = _extract_zhipu_message_content(message)
    usage_data = data.get("usage", {}) or {}
    await record_usage_event(
        provider="zhipu",
        model=str(data.get("model") or model or DEFAULT_ZHIPU_VISION_MODEL),
        usage={
            "prompt_tokens": int(usage_data.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage_data.get("completion_tokens", 0) or 0),
        },
        kind="multimodal",
    )
    return _finalize_text(content, json_mode=json_mode)


def _build_minimax_multimodal_content(
    *,
    prompt: str,
    image_paths: list[Path],
    images_b64: list[str],
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [{"type": "text", "text": str(prompt or "").strip()}]
    for path, image in zip(image_paths, images_b64, strict=False):
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": _guess_media_type(path), "data": image},
            }
        )
    return content


def _resolve_minimax_multimodal_model(model: str) -> str:
    normalized = str(model or "").strip().lower()
    if normalized == "minimax-m3":
        return "MiniMax-M3"
    return "MiniMax-M3"


def _guess_media_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _build_codex_multimodal_prompt(prompt: str, *, json_mode: bool) -> str:
    instructions = [
        "Complete the visual task below using the attached image files.",
        "Use the images as the source of truth for visual details.",
        "Do not ask for clarification.",
    ]
    if json_mode:
        instructions.extend(
            [
                'Return only valid JSON as {"payload_json":"<final_json_minified>"} with no markdown fences.',
                'The value of "payload_json" must itself be valid minified JSON for the final result.',
            ]
        )
    else:
        instructions.append("Return only the final answer with no preamble.")
    return "\n\n".join([*instructions, "USER REQUEST:", str(prompt or "").strip(), "Produce the answer now."]).strip()


def _resolve_codex_bridge_exec_url() -> str:
    explicit = str(os.getenv("ROUGHCUT_MULTIMODAL_CODEX_BRIDGE_URL", "") or "").strip()
    if explicit:
        return explicit
    proxy_url = resolve_codex_proxy_url()
    if proxy_url.endswith("/v1/codex/exec"):
        return proxy_url
    return ""


def _build_zhipu_multimodal_content(
    *,
    prompt: str,
    image_paths: list[Path],
    images_b64: list[str],
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = []
    for path, image in zip(image_paths, images_b64, strict=False):
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{_guess_media_type(path)};base64,{image}",
                },
            }
        )
    content.append({"type": "text", "text": str(prompt or "").strip()})
    return content


def _extract_zhipu_message_content(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "").strip()
    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


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


def _resolve_chat_api_endpoint(provider: str) -> tuple[str, str]:
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
    if provider == "zhipu":
        return (
            normalize_zhipu_base_url(settings.zhipu_base_url),
            resolve_credential(
                mode=settings.zhipu_auth_mode,
                direct_value=settings.zhipu_api_key,
                helper_command=settings.zhipu_api_key_helper,
                provider_name="Zhipu",
            ),
        )
    raise ValueError(f"Unsupported chat API provider: {provider}")


def _finalize_text(text: str, *, json_mode: bool) -> str:
    cleaned = _strip_reasoning_tags(str(text).strip())
    if json_mode:
        try:
            return extract_json_text(cleaned)
        except Exception:
            return json.dumps({"text": cleaned}, ensure_ascii=False)
    return cleaned


async def _resolve_vision_model(*, provider: str | None = None) -> str:
    global _VISION_MODEL_CACHE
    if provider is None and _VISION_MODEL_CACHE:
        return _VISION_MODEL_CACHE

    settings = get_settings()
    if settings.vision_model and _is_provider_compatible_multimodal_model(provider or settings.active_reasoning_provider, settings.vision_model):
        if provider is None:
            _VISION_MODEL_CACHE = settings.vision_model
        return settings.vision_model

    active_provider = (provider or settings.active_reasoning_provider).lower()
    if active_provider != "ollama":
        if _is_provider_compatible_multimodal_model(active_provider, settings.active_vision_model):
            if provider is None:
                _VISION_MODEL_CACHE = settings.active_vision_model
                return _VISION_MODEL_CACHE
            return settings.active_vision_model
        default_model = _default_multimodal_model_for_provider(active_provider)
        if default_model:
            if provider is None:
                _VISION_MODEL_CACHE = default_model
                return _VISION_MODEL_CACHE
            return default_model
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
