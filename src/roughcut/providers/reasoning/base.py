from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | str
    raw_arguments: str = ""
    type: str = "function"


@dataclass
class ReasoningResponse:
    content: str
    usage: dict[str, int]
    model: str
    raw_content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_json(self) -> Any:
        import json

        return json.loads(extract_json_text(self.content))


def strip_reasoning_tags(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()


def extract_json_text(content: str) -> str:
    text = strip_reasoning_tags(content)

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    try:
        import json

        json.loads(text)
        return text
    except Exception:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    object_start = text.find("{")
    array_start = text.find("[")
    starts = [pos for pos in (object_start, array_start) if pos != -1]
    if starts:
        start = min(starts)
        candidate = text[start:].strip()
        decoder = json.JSONDecoder()
        parsed, end = decoder.raw_decode(candidate)
        return json.dumps(parsed, ensure_ascii=False)

    raise ValueError("No JSON payload found in model response")


class ReasoningProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        """Complete a chat conversation."""

    async def complete_with_tools(
        self,
        messages: list[Message],
        *,
        tools: list[ToolDefinition],
        tool_choice: str = "auto",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> ReasoningResponse:
        raise NotImplementedError(f"{type(self).__name__} does not support tool calling")
