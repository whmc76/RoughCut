from __future__ import annotations

import openai

from roughcut.config import get_settings
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse, strip_reasoning_tags
from roughcut.usage import record_usage_event


class MiniMaxReasoningProvider(ReasoningProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.minimax_api_key
        self._base_url = settings.minimax_base_url.rstrip("/")
        self._model = settings.active_reasoning_model

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        kwargs: dict = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        client = openai.AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        try:
            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
            await record_usage_event(
                provider="minimax",
                model=response.model,
                usage=usage,
                kind="reasoning",
            )
            raw_content = choice.message.content or ""
            return ReasoningResponse(
                content=strip_reasoning_tags(raw_content),
                usage=usage,
                model=response.model,
                raw_content=raw_content,
            )
        finally:
            await client.close()
