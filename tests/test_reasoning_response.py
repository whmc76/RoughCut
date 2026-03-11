from __future__ import annotations

from roughcut.providers.reasoning.base import ReasoningResponse


def test_as_json_accepts_markdown_fenced_json():
    response = ReasoningResponse(
        content='```json\n{"preset_name":"unboxing_upgrade"}\n```',
        usage={},
        model="test",
    )
    assert response.as_json()["preset_name"] == "unboxing_upgrade"


def test_as_json_accepts_think_plus_fenced_json():
    response = ReasoningResponse(
        content='<think>analysis</think>\n```json\n{"subject_brand":"FAS"}\n```',
        usage={},
        model="test",
    )
    assert response.as_json()["subject_brand"] == "FAS"
