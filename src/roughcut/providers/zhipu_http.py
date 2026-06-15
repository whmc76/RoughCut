from __future__ import annotations

import asyncio
import json
import time
import uuid
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpx


_ZHIPU_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
_ZHIPU_DEFAULT_COOLDOWN_SECONDS = 30.0
_ZHIPU_MAX_CONCURRENCY = 1
_ZHIPU_PROVIDER_COOLDOWNS: dict[str, tuple[float, str]] = {}
_ZHIPU_PROVIDER_SEMAPHORES: dict[str, tuple[int, asyncio.Semaphore]] = {}
_ZHIPU_STATE_LOCK = Lock()


def build_zhipu_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {str(api_key or '').strip()}",
        "Content-Type": "application/json",
    }


def build_zhipu_request_context() -> dict[str, str]:
    request_id = uuid.uuid4().hex
    return {
        "request_id": request_id,
        "user_id": f"roughcut-{request_id[:16]}",
    }


async def post_zhipu_json(
    *,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout_sec: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    attempts = max(1, int(max_attempts))
    provider_key = _provider_key_for_url(url)
    async with httpx.AsyncClient(timeout=max(5, int(timeout_sec))) as client:
        async with _provider_semaphore(provider_key):
            for attempt in range(1, attempts + 1):
                await _wait_for_provider_cooldown(provider_key)
                try:
                    response = await client.post(url, headers=headers, json=json_payload)
                    if response.status_code in _ZHIPU_TRANSIENT_STATUS_CODES:
                        _record_provider_cooldown(
                            provider_key,
                            retry_after_seconds=_retry_delay_seconds(response=response, attempt=attempt),
                            detail=_response_detail(response),
                        )
                        if attempt < attempts:
                            await asyncio.sleep(_retry_delay_seconds(response=response, attempt=attempt))
                            continue
                    _raise_for_status_with_diagnostics(response)
                    payload = response.json()
                    return payload if isinstance(payload, dict) else {}
                except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                    last_error = exc
                    _record_provider_cooldown(
                        provider_key,
                        retry_after_seconds=_backoff_seconds(attempt),
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                    if attempt >= attempts:
                        raise
                    await asyncio.sleep(_backoff_seconds(attempt))
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    status = int(exc.response.status_code)
                    if status in _ZHIPU_TRANSIENT_STATUS_CODES:
                        _record_provider_cooldown(
                            provider_key,
                            retry_after_seconds=_retry_delay_seconds(response=exc.response, attempt=attempt),
                            detail=_response_detail(exc.response),
                        )
                    if status not in _ZHIPU_TRANSIENT_STATUS_CODES or attempt >= attempts:
                        raise
                    await asyncio.sleep(_retry_delay_seconds(response=exc.response, attempt=attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Zhipu request failed without a response")


def _provider_key_for_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    scheme = str(parsed.scheme or "https").strip().lower() or "https"
    netloc = str(parsed.netloc or "").strip().lower()
    return f"{scheme}://{netloc}" if netloc else "zhipu"


def _provider_semaphore(provider_key: str) -> asyncio.Semaphore:
    with _ZHIPU_STATE_LOCK:
        current = _ZHIPU_PROVIDER_SEMAPHORES.get(provider_key)
        if current is None or current[0] != _ZHIPU_MAX_CONCURRENCY:
            semaphore = asyncio.Semaphore(_ZHIPU_MAX_CONCURRENCY)
            _ZHIPU_PROVIDER_SEMAPHORES[provider_key] = (_ZHIPU_MAX_CONCURRENCY, semaphore)
            return semaphore
        return current[1]


async def _wait_for_provider_cooldown(provider_key: str) -> None:
    while True:
        remaining = _provider_cooldown_remaining_seconds(provider_key)
        if remaining <= 0.0:
            return
        await asyncio.sleep(remaining)


def _provider_cooldown_remaining_seconds(provider_key: str) -> float:
    now = time.monotonic()
    with _ZHIPU_STATE_LOCK:
        cooldown = _ZHIPU_PROVIDER_COOLDOWNS.get(provider_key)
        if cooldown is None:
            return 0.0
        until, _detail = cooldown
        if until <= now:
            _ZHIPU_PROVIDER_COOLDOWNS.pop(provider_key, None)
            return 0.0
        return max(0.0, until - now)


def provider_cooldown_remaining_seconds_for_url(url: str) -> float:
    return _provider_cooldown_remaining_seconds(_provider_key_for_url(url))


def _record_provider_cooldown(provider_key: str, *, retry_after_seconds: float, detail: str) -> None:
    seconds = max(_ZHIPU_DEFAULT_COOLDOWN_SECONDS, float(retry_after_seconds or 0.0))
    until = time.monotonic() + seconds
    detail_text = " ".join(str(detail or "").strip().split())[:240]
    with _ZHIPU_STATE_LOCK:
        current = _ZHIPU_PROVIDER_COOLDOWNS.get(provider_key)
        if current is None or current[0] < until:
            _ZHIPU_PROVIDER_COOLDOWNS[provider_key] = (until, detail_text)


def _response_detail(response: httpx.Response) -> str:
    try:
        body_text = response.text
    except Exception:
        body_text = ""
    detail = body_text or response.reason_phrase or f"http {response.status_code}"
    return detail


def _raise_for_status_with_diagnostics(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        diagnostics = zhipu_response_diagnostics(response)
        message = str(exc)
        extras: list[str] = []
        if diagnostics.get("error_code"):
            extras.append(f"zhipu_error_code={diagnostics['error_code']}")
        if diagnostics.get("error_message"):
            extras.append(f"zhipu_error_message={diagnostics['error_message']}")
        if diagnostics.get("retry_after_seconds") is not None:
            extras.append(f"retry_after_seconds={diagnostics['retry_after_seconds']}")
        if diagnostics.get("x_log_id"):
            extras.append(f"x_log_id={diagnostics['x_log_id']}")
        if extras:
            message = f"{message} [{' | '.join(extras)}]"
        enriched = httpx.HTTPStatusError(message, request=exc.request, response=exc.response)
        raise enriched from exc


def zhipu_response_diagnostics(response: httpx.Response) -> dict[str, Any]:
    body_text = _response_detail(response)
    payload: dict[str, Any] | None = None
    try:
        loaded = response.json()
        if isinstance(loaded, dict):
            payload = loaded
    except Exception:
        payload = None
    error_block = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    return {
        "status_code": int(response.status_code),
        "error_code": str(error_block.get("code") or "").strip() or None,
        "error_message": str(error_block.get("message") or "").strip() or None,
        "retry_after_seconds": _parse_retry_after_seconds(response.headers),
        "x_log_id": str(response.headers.get("x-log-id") or "").strip() or None,
        "body_excerpt": _body_excerpt(body_text),
    }


def _body_excerpt(body_text: str) -> str | None:
    normalized = " ".join(str(body_text or "").strip().split())
    if not normalized:
        return None
    if normalized.startswith("{"):
        try:
            loaded = json.loads(normalized)
            normalized = json.dumps(loaded, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass
    return normalized[:240]


def _retry_delay_seconds(*, response: httpx.Response, attempt: int) -> float:
    retry_after = _parse_retry_after_seconds(response.headers)
    if retry_after is not None:
        return retry_after
    return _backoff_seconds(attempt)


def _parse_retry_after_seconds(headers: httpx.Headers) -> float | None:
    for name in ("retry-after-ms", "x-retry-after-ms"):
        raw = str(headers.get(name) or "").strip()
        if not raw:
            continue
        try:
            return max(0.0, float(raw) / 1000.0)
        except Exception:
            continue
    raw = str(headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    if value >= 1000:
        return value / 1000.0
    return max(0.0, value)


def _backoff_seconds(attempt: int) -> float:
    normalized_attempt = max(1, int(attempt))
    return min(8.0, 0.75 * (2 ** (normalized_attempt - 1)))
