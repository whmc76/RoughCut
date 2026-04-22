from __future__ import annotations

import asyncio
import json
from pathlib import Path

import openai

from roughcut.config import get_settings, uses_codex_auth_helper
from roughcut.host.codex_bridge import run_codex_exec
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
    _CODEX_JSON_WRAPPER_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "payload_json": {"type": "string"},
        },
        "required": ["payload_json"],
    }

    def __init__(self) -> None:
        settings = get_settings()
        self._bridge_mode = (
            uses_codex_auth_helper(settings)
            and not str(settings.openai_api_key or "").strip()
        )
        self._model = settings.active_reasoning_model
        self._client = None
        if not self._bridge_mode:
            self._client = openai.AsyncOpenAI(
                api_key=resolve_credential(
                    mode=settings.openai_auth_mode,
                    direct_value=settings.openai_api_key,
                    helper_command=settings.openai_api_key_helper,
                    provider_name="OpenAI",
                ),
                base_url=settings.openai_base_url.rstrip("/"),
            )

    @staticmethod
    def _build_codex_prompt(messages: list[Message], *, json_mode: bool) -> str:
        system_messages = [
            str(getattr(message, "content", "") or "").strip()
            for message in messages
            if str(getattr(message, "role", "") or "").strip().lower() in {"system", "developer"}
        ]
        user_messages = [
            str(getattr(message, "content", "") or "").strip()
            for message in messages
            if str(getattr(message, "role", "") or "").strip().lower() not in {"system", "developer"}
        ]
        instructions = [
            "Complete the task below directly.",
            "Follow the SYSTEM INSTRUCTIONS as highest priority.",
            "Answer the USER REQUEST now.",
            "Do not ask for more context or clarification.",
        ]
        if json_mode:
            instructions.extend(
                [
                    'Return only valid JSON as {"payload_json":"<final_json_minified>"} with no markdown fences.',
                    "Do not output acknowledgements like Understood.",
                    'The value of "payload_json" must itself be valid minified JSON for the final result.',
                ]
            )
        else:
            instructions.append("Return only the final assistant message. Do not add preambles, status text, or meta commentary.")
        return "\n\n".join(
            [
                *instructions,
                "SYSTEM INSTRUCTIONS:",
                "\n\n".join(system_messages) or "(none)",
                "USER REQUEST:",
                "\n\n".join(user_messages) or "(none)",
                "Produce the answer now.",
            ]
        ).strip()

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        if self._bridge_mode:
            del temperature, max_tokens
            result = await asyncio.to_thread(
                run_codex_exec,
                {
                    "repo_root": str(Path.cwd()),
                    "prompt": self._build_codex_prompt(messages, json_mode=json_mode),
                    "model": self._model,
                    "timeout_sec": 300,
                    "output_schema": self._CODEX_JSON_WRAPPER_SCHEMA if json_mode else None,
                },
            )
            raw_content = str(result.get("stdout") or result.get("excerpt") or "").strip()
            if json_mode:
                payload = json.loads(raw_content)
                raw_content = str(payload.get("payload_json") or "").strip()
            usage = {"prompt_tokens": 0, "completion_tokens": 0}
            await record_usage_event(
                provider="openai",
                model=self._model,
                usage=usage,
                kind="reasoning",
            )
            return ReasoningResponse(
                content=raw_content,
                usage=usage,
                model=self._model,
                raw_content=raw_content,
            )

        kwargs: dict = {
            "model": self._model,
            "input": build_message_input(messages),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        text_options = build_text_options(json_mode=json_mode)
        if text_options:
            kwargs["text"] = text_options
        reasoning_options = build_reasoning_options(
            self._model,
            effort=str(getattr(get_settings(), "active_reasoning_effort", "medium") or "medium"),
        )
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
            raw_content=extract_response_output_text(response),
        )
