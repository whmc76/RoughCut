from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from roughcut.pipeline import steps


@pytest.mark.asyncio
async def test_source_context_feedback_failure_preserves_content_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_verification_bundle(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("ConnectError: All connection attempts failed")

    monkeypatch.setattr(steps, "llm_task_route", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(steps, "build_review_feedback_verification_bundle", failing_verification_bundle)

    profile, feedback = await steps._apply_source_context_feedback_to_content_profile(
        None,
        job=SimpleNamespace(source_name="demo.mp4", workflow_template="vlog_daily"),
        step=SimpleNamespace(metadata_={}),
        settings=SimpleNamespace(),
        content_profile={"summary": "fallback profile"},
        source_context={
            "manual_video_summary": "explicit task summary",
            "strategy_classification": {"primary_type": "vlog"},
        },
        transcript_excerpt="",
        include_research=False,
    )

    assert feedback == {}
    assert profile["summary"] == "fallback profile"
    assert profile["source_context"]["manual_video_summary"] == "explicit task summary"
    assert profile["source_context"]["strategy_classification"] == {"primary_type": "vlog"}
    assert profile["source_context"]["source_context_feedback_error"].startswith("RuntimeError: ConnectError")
