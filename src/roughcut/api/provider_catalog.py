from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx

from roughcut.config import TRANSCRIPTION_MODEL_OPTIONS, get_settings
from roughcut.providers.auth import resolve_credential

_MODEL_CATALOG_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_MODEL_CATALOG_LOCK = Lock()


def build_service_status_payload() -> dict[str, Any]:
    settings = get_settings()
    checked_at = _now_iso()
    services = {
        "ollama": _probe_local_service(
            name="ollama",
            base_url=settings.ollama_base_url,
            url=f"{settings.ollama_base_url.rstrip('/')}/api/tags",
        ),
        "qwen_asr": _probe_local_service(
            name="qwen_asr",
            base_url=settings.qwen_asr_api_base_url,
            url=f"{settings.qwen_asr_api_base_url.rstrip('/')}/health",
        ),
        "openai": _credential_status(
            name="openai",
            base_url=settings.openai_base_url,
            configured=bool(str(settings.openai_api_key or "").strip() or str(settings.openai_api_key_helper or "").strip()),
        ),
        "anthropic": _credential_status(
            name="anthropic",
            base_url=settings.anthropic_base_url,
            configured=bool(str(settings.anthropic_api_key or "").strip() or str(settings.anthropic_api_key_helper or "").strip()),
        ),
        "minimax": _credential_status(
            name="minimax",
            base_url=settings.minimax_base_url,
            configured=bool(str(settings.minimax_api_key or "").strip()),
        ),
    }
    return {
        "checked_at": checked_at,
        "services": services,
    }


def get_model_catalog_payload(*, provider: str, kind: str, refresh: bool) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    normalized_kind = str(kind or "").strip().lower()
    cache_key = (normalized_provider, normalized_kind)

    if not refresh:
        cached = _get_cached_catalog(cache_key)
        if cached is not None:
            return cached

    try:
        models = _fetch_models(provider=normalized_provider, kind=normalized_kind)
        payload = {
            "provider": normalized_provider,
            "kind": normalized_kind,
            "models": models,
            "source": "live",
            "refreshed_at": _now_iso(),
            "status": "ok",
            "error": None,
        }
        _store_cached_catalog(cache_key, payload)
        return payload
    except Exception as exc:
        cached = _get_cached_catalog(cache_key)
        if cached is not None:
            return {
                **cached,
                "source": "cache",
                "status": "error",
                "error": str(exc),
            }
        return {
            "provider": normalized_provider,
            "kind": normalized_kind,
            "models": [],
            "source": "live",
            "refreshed_at": _now_iso(),
            "status": "error",
            "error": str(exc),
        }


def _fetch_models(*, provider: str, kind: str) -> list[str]:
    if provider == "ollama":
        return _fetch_ollama_models()
    if provider in TRANSCRIPTION_MODEL_OPTIONS and provider != "openai":
        return sorted(TRANSCRIPTION_MODEL_OPTIONS[provider])
    if provider == "openai":
        models = _fetch_openai_compatible_models(provider="openai")
        if kind == "transcription":
            transcribe_models = [model for model in models if "transcribe" in model]
            return sorted(transcribe_models or TRANSCRIPTION_MODEL_OPTIONS["openai"])
        return sorted(models)
    if provider == "minimax":
        return sorted(_fetch_openai_compatible_models(provider="minimax"))
    if provider == "anthropic":
        return sorted(_fetch_anthropic_models())
    raise ValueError(f"Unsupported provider: {provider}")


def _fetch_ollama_models() -> list[str]:
    settings = get_settings()
    response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=10)
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}")
    data = response.json()
    model_names = sorted({str(item.get("name") or "").strip() for item in data.get("models", []) if str(item.get("name") or "").strip()})
    return model_names


def _fetch_openai_compatible_models(*, provider: str) -> list[str]:
    settings = get_settings()
    if provider == "openai":
        base_url = settings.openai_base_url.rstrip("/")
        token = resolve_credential(
            mode=settings.openai_auth_mode,
            direct_value=settings.openai_api_key,
            helper_command=settings.openai_api_key_helper,
            provider_name="OpenAI",
        )
    elif provider == "minimax":
        base_url = settings.minimax_base_url.rstrip("/")
        token = str(settings.minimax_api_key or "").strip()
        if not token:
            raise ValueError("MiniMax API credential is not configured")
    else:
        raise ValueError(f"Unsupported OpenAI-compatible provider: {provider}")

    response = httpx.get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{provider} models request returned HTTP {response.status_code}")
    data = response.json()
    return [str(item.get("id") or "").strip() for item in data.get("data", []) if str(item.get("id") or "").strip()]


def _fetch_anthropic_models() -> list[str]:
    settings = get_settings()
    token = resolve_credential(
        mode=settings.anthropic_auth_mode,
        direct_value=settings.anthropic_api_key,
        helper_command=settings.anthropic_api_key_helper,
        provider_name="Anthropic",
    )
    response = httpx.get(
        f"{settings.anthropic_base_url.rstrip('/')}/v1/models",
        headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": token,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"anthropic models request returned HTTP {response.status_code}")
    data = response.json()
    return [str(item.get("id") or "").strip() for item in data.get("data", []) if str(item.get("id") or "").strip()]


def _probe_local_service(*, name: str, base_url: str, url: str) -> dict[str, Any]:
    normalized_base = str(base_url or "").strip()
    if not normalized_base:
        return {
            "name": name,
            "base_url": "",
            "status": "not_configured",
            "error": "base_url is empty",
        }
    try:
        response = httpx.get(url, timeout=5)
        if response.status_code >= 400:
            return {
                "name": name,
                "base_url": normalized_base,
                "status": "unreachable",
                "error": f"HTTP {response.status_code}",
            }
        return {
            "name": name,
            "base_url": normalized_base,
            "status": "ok",
            "error": None,
        }
    except Exception as exc:
        return {
            "name": name,
            "base_url": normalized_base,
            "status": "unreachable",
            "error": str(exc),
        }


def _credential_status(*, name: str, base_url: str, configured: bool) -> dict[str, Any]:
    return {
        "name": name,
        "base_url": str(base_url or "").strip(),
        "status": "configured" if configured else "not_configured",
        "error": None if configured else "credential is missing",
    }


def _get_cached_catalog(cache_key: tuple[str, str]) -> dict[str, Any] | None:
    with _MODEL_CATALOG_LOCK:
        cached = _MODEL_CATALOG_CACHE.get(cache_key)
        if cached is None:
            return None
        return dict(cached)


def _store_cached_catalog(cache_key: tuple[str, str], payload: dict[str, Any]) -> None:
    with _MODEL_CATALOG_LOCK:
        _MODEL_CATALOG_CACHE[cache_key] = dict(payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
