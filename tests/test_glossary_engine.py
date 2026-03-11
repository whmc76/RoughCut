from __future__ import annotations

import pytest

from roughcut.review.glossary_engine import apply_corrections_to_text
from roughcut.db.models import SubtitleCorrection


def _mock_correction(original: str, suggested: str, applied: bool = True, decision: str = "accepted"):
    return SubtitleCorrection(
        original_span=original,
        suggested_span=suggested,
        change_type="glossary",
        confidence=1.0,
        auto_applied=applied,
        human_decision=decision,
        human_override=None,
    )


def test_apply_corrections_basic():
    text = "这款GPT4模型效果很好"
    corrections = [_mock_correction("GPT4", "GPT-4")]
    result = apply_corrections_to_text(text, corrections)
    assert result == "这款GPT-4模型效果很好"


def test_apply_corrections_with_override():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4")
    c.human_override = "GPT-4o"
    result = apply_corrections_to_text(text, [c])
    assert result == "这款GPT-4o模型效果很好"


def test_apply_corrections_pending_not_applied():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4", applied=False, decision="pending")
    result = apply_corrections_to_text(text, [c])
    assert result == text  # Not applied


def test_apply_corrections_rejected_not_applied():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4", applied=False, decision="rejected")
    result = apply_corrections_to_text(text, [c])
    assert result == text
