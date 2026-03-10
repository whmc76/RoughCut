from __future__ import annotations

import anthropic

from fastcut.config import get_settings
from fastcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse


class AnthropicReasoningProvider(ReasoningProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.reasoning_model

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        system_msgs = [m.content for m in messages if m.role == "system"]
        chat_msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        system_text = "\n\n".join(system_msgs) if system_msgs else None

        if json_mode:
            if chat_msgs:
                chat_msgs[-1]["content"] += "\n\nRespond with valid JSON only."

        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_msgs,
        }
        if system_text:
            kwargs["system"] = system_text

        response = await self._client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
        }
        return ReasoningResponse(content=content, usage=usage, model=response.model)
