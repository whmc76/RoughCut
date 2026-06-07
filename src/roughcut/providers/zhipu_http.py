from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx


_ZHIPU_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}


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
    async with httpx.AsyncClient(timeout=max(5, int(timeout_sec))) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(url, headers=headers, json=json_payload)
                if response.status_code in _ZHIPU_TRANSIENT_STATUS_CODES and attempt < attempts:
                    await asyncio.sleep(_retry_delay_seconds(response=response, attempt=attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                await asyncio.sleep(_backoff_seconds(attempt))
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = int(exc.response.status_code)
                if status not in _ZHIPU_TRANSIENT_STATUS_CODES or attempt >= attempts:
                    raise
                await asyncio.sleep(_retry_delay_seconds(response=exc.response, attempt=attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Zhipu request failed without a response")


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
