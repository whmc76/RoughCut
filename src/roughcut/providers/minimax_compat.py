from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def resolve_minimax_anthropic_base_url(*, base_url: str, api_host: str) -> str:
    for candidate in (str(api_host or "").strip(), str(base_url or "").strip()):
        normalized = _normalize_minimax_anthropic_candidate(candidate)
        if normalized:
            return normalized
    raise ValueError("MiniMax Anthropic-compatible base URL is not configured")


def _normalize_minimax_anthropic_candidate(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""

    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    if not path.endswith("/anthropic"):
        path = f"{path}/anthropic" if path else "/anthropic"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment)).rstrip("/")
