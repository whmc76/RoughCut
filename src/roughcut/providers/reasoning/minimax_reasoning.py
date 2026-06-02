from __future__ import annotations

import httpx

from roughcut.config import get_settings
from roughcut.providers.minimax_compat import resolve_minimax_anthropic_base_url
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse, strip_reasoning_tags
from roughcut.usage import record_usage_event

_MINIMAX_REASONING_TIMEOUT_SECONDS = 120


class MiniMaxReasoningProvider(ReasoningProvider):
    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.minimax_api_key
        self._base_url = resolve_minimax_anthropic_base_url(
            base_url=settings.minimax_base_url,
            api_host=settings.minimax_api_host,
        )
        self._model = model or settings.active_reasoning_model

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        system_messages = [m.content for m in messages if m.role == "system"]
        chat_messages = [_build_minimax_message_block(message) for message in messages if message.role != "system"]
        if json_mode and chat_messages:
            last_message = chat_messages[-1]
            content_blocks = list(last_message.get("content") or [])
            if content_blocks and content_blocks[-1].get("type") == "text":
                content_blocks[-1] = {
                    "type": "text",
                    "text": f"{content_blocks[-1].get('text', '')}\n\nRespond with valid JSON only.",
                }
                last_message["content"] = content_blocks

        payload: dict[str, object] = {
            "model": self._model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_messages:
            payload["system"] = "\n\n".join(str(text or "").strip() for text in system_messages if str(text or "").strip())

        headers = {
            "content-type": "application/json",
            "x-api-key": self._api_key,
            "authorization": f"Bearer {self._api_key}",
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=_MINIMAX_REASONING_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self._base_url}/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        raw_content = "".join(
            str(part.get("text") or "")
            for part in list(data.get("content") or [])
            if str(part.get("type") or "").strip() == "text"
        )
        usage_data = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": int(usage_data.get("input_tokens", 0) or 0),
            "completion_tokens": int(usage_data.get("output_tokens", 0) or 0),
        }
        await record_usage_event(
            provider="minimax",
            model=str(data.get("model") or self._model),
            usage=usage,
            kind="reasoning",
        )
        return ReasoningResponse(
            content=strip_reasoning_tags(raw_content),
            usage=usage,
            model=str(data.get("model") or self._model),
            raw_content=raw_content,
        )


def _build_minimax_message_block(message: Message) -> dict[str, object]:
    return {
        "role": message.role,
        "content": [{"type": "text", "text": str(message.content or "")}],
    }
