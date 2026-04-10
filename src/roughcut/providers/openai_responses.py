from __future__ import annotations

from typing import Any, Iterable

from roughcut.providers.reasoning.base import Message


def build_reasoning_options(model: str, *, effort: str = "medium") -> dict[str, str] | None:
    normalized = str(model or "").strip().lower()
    if not normalized:
        return None
    if normalized.startswith("gpt-5") or "codex" in normalized:
        return {"effort": effort}
    return None


def build_text_options(*, json_mode: bool, verbosity: str | None = None) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if json_mode:
        payload["format"] = {"type": "json_object"}
    if verbosity:
        payload["verbosity"] = verbosity
    return payload or None


def build_message_input(messages: Iterable[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(getattr(message, "role", "") or "user").strip().lower()
        if role not in {"system", "developer", "user", "assistant"}:
            role = "user"
        items.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": str(getattr(message, "content", "") or "")}],
            }
        )
    return items


def build_multimodal_input(prompt: str, image_urls: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": str(prompt or "")}]
    for image_url in image_urls:
        normalized_url = str(image_url or "").strip()
        if not normalized_url:
            continue
        content.append(
            {
                "type": "input_image",
                "image_url": normalized_url,
                "detail": "high",
            }
        )
    return [{"role": "user", "content": content}]


def extract_response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0}
    return {
        "prompt_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def extract_response_output_text(response: Any) -> str:
    text = str(getattr(response, "output_text", "") or "").strip()
    if text:
        return text

    chunks: list[str] = []
    for item in list(getattr(response, "output", []) or []):
        for content in list(getattr(item, "content", []) or []):
            text_value = str(getattr(content, "text", "") or "").strip()
            if text_value:
                chunks.append(text_value)
    return "\n".join(chunks).strip()
