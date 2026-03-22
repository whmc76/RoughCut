from __future__ import annotations

import httpx

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse
from roughcut.usage import record_usage_event


class AnthropicReasoningProvider(ReasoningProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.anthropic_base_url.rstrip("/")
        self._model = settings.active_reasoning_model
        self._credential = resolve_credential(
            mode=settings.anthropic_auth_mode,
            direct_value=settings.anthropic_api_key,
            helper_command=settings.anthropic_api_key_helper,
            provider_name="Anthropic",
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        system_msgs = [m.content for m in messages if m.role == "system"]
        user_msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        if json_mode and user_msgs:
            user_msgs[-1]["content"] += "\n\nRespond with valid JSON only."

        payload: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
        }
        if system_msgs:
            payload["system"] = "\n\n".join(system_msgs)

        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self._credential,
            "authorization": f"Bearer {self._credential}",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self._base_url}/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        parts = data.get("content", []) or []
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        usage_data = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": int(usage_data.get("input_tokens", 0)),
            "completion_tokens": int(usage_data.get("output_tokens", 0)),
        }
        await record_usage_event(
            provider="anthropic",
            model=str(data.get("model", self._model)),
            usage=usage,
            kind="reasoning",
        )
        return ReasoningResponse(
            content=text,
            usage=usage,
            model=data.get("model", self._model),
        )
