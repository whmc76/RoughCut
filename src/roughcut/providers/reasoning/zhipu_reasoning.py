from __future__ import annotations

from roughcut.config import DEFAULT_ZHIPU_REASONING_MODEL, get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.reasoning.base import Message, ReasoningProvider, ReasoningResponse, ToolCall, ToolDefinition, strip_reasoning_tags
from roughcut.providers.zhipu_compat import resolve_zhipu_reasoning_base_url
from roughcut.providers.zhipu_http import build_zhipu_headers, build_zhipu_request_context, post_zhipu_json
from roughcut.usage import record_usage_event

_ZHIPU_REASONING_TIMEOUT_SECONDS = 600


class ZhipuReasoningProvider(ReasoningProvider):
    def __init__(self, *, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = resolve_credential(
            mode=settings.zhipu_auth_mode,
            direct_value=settings.zhipu_api_key,
            helper_command=settings.zhipu_api_key_helper,
            provider_name="Zhipu",
        )
        self._model = model or settings.active_reasoning_model or DEFAULT_ZHIPU_REASONING_MODEL
        self._base_url = resolve_zhipu_reasoning_base_url(
            base_url=settings.zhipu_base_url,
            coding_base_url=getattr(settings, "zhipu_coding_base_url", ""),
            model=self._model,
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        effort = str(getattr(get_settings(), "active_reasoning_effort", "low") or "low").strip().lower()
        enable_thinking = _should_enable_zhipu_thinking(
            model=self._model,
            effort=effort,
            json_mode=json_mode,
        )
        data = await self._request_completion(
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            enable_thinking=enable_thinking,
        )
        choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
        message = choice.get("message") or {}
        raw_content = _extract_message_content(message)
        if not raw_content and enable_thinking and str(message.get("reasoning_content") or "").strip():
            data = await self._request_completion(
                messages=messages,
                temperature=temperature,
                json_mode=json_mode,
                enable_thinking=False,
            )
            choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
            message = choice.get("message") or {}
            raw_content = _extract_message_content(message)

        usage_data = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": int(usage_data.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage_data.get("completion_tokens", 0) or 0),
        }
        await record_usage_event(
            provider="zhipu",
            model=str(data.get("model") or self._model),
            usage=usage,
            kind="reasoning",
        )
        return ReasoningResponse(
            content=strip_reasoning_tags(raw_content),
            usage=usage,
            model=str(data.get("model") or self._model),
            raw_content=raw_content,
            tool_calls=_extract_tool_calls(message),
        )

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition],
        tool_choice: str = "auto",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        effort = str(getattr(get_settings(), "active_reasoning_effort", "low") or "low").strip().lower()
        enable_thinking = _should_enable_zhipu_thinking(
            model=self._model,
            effort=effort,
            json_mode=json_mode,
        )
        data = await self._request_completion(
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            enable_thinking=enable_thinking,
            tools=tools,
            tool_choice=tool_choice,
        )
        choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
        message = choice.get("message") or {}
        raw_content = _extract_message_content(message)
        tool_calls = _extract_tool_calls(message)
        if not raw_content and not tool_calls and enable_thinking and str(message.get("reasoning_content") or "").strip():
            data = await self._request_completion(
                messages=messages,
                temperature=temperature,
                json_mode=json_mode,
                enable_thinking=False,
                tools=tools,
                tool_choice=tool_choice,
            )
            choice = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
            message = choice.get("message") or {}
            raw_content = _extract_message_content(message)
            tool_calls = _extract_tool_calls(message)
        usage_data = data.get("usage", {}) or {}
        usage = {
            "prompt_tokens": int(usage_data.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage_data.get("completion_tokens", 0) or 0),
        }
        await record_usage_event(
            provider="zhipu",
            model=str(data.get("model") or self._model),
            usage=usage,
            kind="reasoning",
        )
        return ReasoningResponse(
            content=strip_reasoning_tags(raw_content),
            usage=usage,
            model=str(data.get("model") or self._model),
            raw_content=raw_content,
            tool_calls=tool_calls,
        )

    async def _request_completion(
        self,
        *,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        enable_thinking: bool,
        tools: list[ToolDefinition] | None = None,
        tool_choice: str = "auto",
    ) -> dict:
        chat_messages = [_build_zhipu_message_block(message) for message in messages]
        if json_mode and chat_messages:
            last_message = chat_messages[-1]
            if isinstance(last_message.get("content"), str):
                last_message["content"] = f"{last_message['content']}\n\nRespond with valid JSON only."

        payload: dict[str, object] = {
            "model": self._model,
            "messages": chat_messages,
            "temperature": temperature,
            **build_zhipu_request_context(),
        }
        payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = [_build_zhipu_tool_block(tool) for tool in tools]
            if str(tool_choice or "").strip():
                payload["tool_choice"] = str(tool_choice or "").strip()

        return await post_zhipu_json(
            url=f"{self._base_url}/chat/completions",
            json_payload=payload,
            headers=build_zhipu_headers(self._api_key),
            timeout_sec=_ZHIPU_REASONING_TIMEOUT_SECONDS,
            max_attempts=3,
        )


def _build_zhipu_message_block(message: Message) -> dict[str, object]:
    return {
        "role": str(message.role or "user").strip().lower() or "user",
        "content": str(message.content or ""),
    }


def _extract_message_content(message: object) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()
    return str(content or "").strip()


def _build_zhipu_tool_block(tool: ToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": str(tool.name or "").strip(),
            "description": str(tool.description or "").strip(),
            "parameters": dict(tool.parameters or {}),
        },
    }


def _extract_tool_calls(message: object) -> list[ToolCall]:
    if not isinstance(message, dict):
        return []
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    parsed: list[ToolCall] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        function_block = item.get("function") if isinstance(item.get("function"), dict) else {}
        raw_arguments = str(function_block.get("arguments") or "").strip()
        arguments: dict[str, object] | str = raw_arguments
        if raw_arguments:
            try:
                loaded = __import__("json").loads(raw_arguments)
                if isinstance(loaded, dict):
                    arguments = loaded
            except Exception:
                arguments = raw_arguments
        parsed.append(
            ToolCall(
                id=str(item.get("id") or "").strip(),
                name=str(function_block.get("name") or "").strip(),
                arguments=arguments,
                raw_arguments=raw_arguments,
                type=str(item.get("type") or "function").strip() or "function",
            )
        )
    return parsed


def _should_enable_zhipu_thinking(
    *,
    effort: str,
    json_mode: bool = False,
    model: str = "",
) -> bool:
    if json_mode:
        return False
    normalized_effort = str(effort or "").strip().lower()
    return normalized_effort in {"medium", "high", "xhigh", "max", "ultracode"}
