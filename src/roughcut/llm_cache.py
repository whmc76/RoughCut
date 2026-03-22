from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from roughcut.config import get_settings

_CACHE_LAYOUT_VERSION = "v1"


def _stable_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_dumps(payload).encode("utf-8")).hexdigest()


def build_cache_key(namespace: str, fingerprint: dict[str, Any]) -> str:
    return digest_payload(
        {
            "layout_version": _CACHE_LAYOUT_VERSION,
            "namespace": str(namespace or "").strip(),
            "fingerprint": fingerprint,
        }
    )


def get_cache_root() -> Path:
    settings = get_settings()
    root = Path(settings.output_dir) / "_cache" / "llm"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_cache_path(namespace: str, key: str) -> Path:
    namespace_dir = get_cache_root() / str(namespace or "default").strip().replace(".", "_")
    namespace_dir.mkdir(parents=True, exist_ok=True)
    return namespace_dir / f"{key}.json"


def _normalize_usage_baseline(usage_baseline: dict[str, Any] | None) -> dict[str, int] | None:
    payload = usage_baseline or {}
    try:
        prompt_tokens = max(0, int(payload.get("prompt_tokens") or 0))
        completion_tokens = max(0, int(payload.get("completion_tokens") or 0))
        calls = max(0, int(payload.get("calls") or 0))
        total_tokens = max(0, int(payload.get("total_tokens") or (prompt_tokens + completion_tokens)))
    except (TypeError, ValueError):
        return None
    if calls <= 0 and total_tokens <= 0:
        return None
    return {
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def load_cached_entry(namespace: str, key: str) -> dict[str, Any] | None:
    path = get_cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    return {
        "namespace": str(payload.get("namespace") or namespace).strip(),
        "key": str(payload.get("key") or key).strip(),
        "result": result,
        "usage_baseline": _normalize_usage_baseline(payload.get("usage_baseline")),
    }


def load_cached_json(namespace: str, key: str) -> dict[str, Any] | None:
    entry = load_cached_entry(namespace, key)
    return dict(entry.get("result") or {}) if entry else None


def save_cached_json(
    namespace: str,
    key: str,
    *,
    fingerprint: dict[str, Any],
    result: dict[str, Any],
    usage_baseline: dict[str, Any] | None = None,
) -> Path:
    path = get_cache_path(namespace, key)
    payload = {
        "namespace": namespace,
        "key": key,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "result": result,
        "usage_baseline": _normalize_usage_baseline(usage_baseline),
    }
    path.write_text(_stable_dumps(payload), encoding="utf-8")
    return path


def build_cache_metadata(
    namespace: str,
    key: str,
    *,
    hit: bool,
    usage_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "namespace": namespace,
        "key": key,
        "hit": bool(hit),
    }
    normalized_usage_baseline = _normalize_usage_baseline(usage_baseline)
    if normalized_usage_baseline:
        metadata["usage_baseline"] = normalized_usage_baseline
    return metadata
