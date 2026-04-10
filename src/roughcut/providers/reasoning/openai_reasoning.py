from __future__ import annotations

import openai

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.openai_responses import (
    build_message_input,
    build_reasoning_options,
    build_text_options,
    extract_response_output_text,
    extract_response_usage,
)
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse
from roughcut.usage import record_usage_event


class OpenAIReasoningProvider(ReasoningProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(
            api_key=resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
            base_url=settings.openai_base_url.rstrip("/"),
        )
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
            "input": build_message_input(messages),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        text_options = build_text_options(json_mode=json_mode)
        if text_options:
            kwargs["text"] = text_options
        reasoning_options = build_reasoning_options(self._model, effort="medium")
        if reasoning_options:
            kwargs["reasoning"] = reasoning_options

        response = await self._client.responses.create(**kwargs)
        usage = extract_response_usage(response)
        await record_usage_event(
            provider="openai",
            model=response.model,
            usage=usage,
            kind="reasoning",
        )
        return ReasoningResponse(
            content=extract_response_output_text(response),
            usage=usage,
            model=response.model,
        )
