from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ReasoningResponse:
    content: str
    usage: dict[str, int]
    model: str

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
