from types import SimpleNamespace
from uuid import uuid4

import pytest

from roughcut.db.models import Artifact
from roughcut.pipeline.steps import (
    _attach_edit_decision_projection_gate_analysis,
    _resolve_auto_smart_cut_rules,
    _merge_automatic_gate_with_subtitle_projection,
)
from roughcut.edit.smart_cut_rules import default_smart_cut_rules_payload


def test_subtitle_projection_gate_is_attached_to_edit_decision_analysis() -> None:
    validation = {
        "blocking": True,
        "blocking_issue_count": 2,
        "warning_issue_count": 1,
        "issue_counts": {"missing_projected_subtitle": 2},
    }
    repair = {
        "repair_requested": True,
        "repair_applied": True,
        "mismatch_detected": True,
        "fallback_used": True,
        "changed": True,
        "input_count": 2,
        "output_count": 3,
        "repair_mode": "source_fallback_remap",
    }
    automatic_gate = _merge_automatic_gate_with_subtitle_projection(
        {"blocking": False, "blocking_reasons": []},
        validation,
    )
    decision = SimpleNamespace(analysis={})

    _attach_edit_decision_projection_gate_analysis(
        decision,
        subtitle_source_projection_validation=validation,
        automatic_gate=automatic_gate,
        subtitle_projection_repair=repair,
    )

    assert decision.analysis["subtitle_source_projection_validation"] == validation
    assert decision.analysis["subtitle_projection_repair"] == repair
    assert decision.analysis["automatic_gate"]["blocking"] is True
    assert decision.analysis["automatic_gate"]["blocking_reasons"] == [
        "subtitle_source_projection_validation_blocking"
    ]


class _FakeResult:
    def __init__(self, artifacts: list[object]) -> None:
        self._artifacts = artifacts

    def scalars(self) -> "_FakeScalarResult":
        return _FakeScalarResult(self._artifacts)


class _FakeScalarResult:
    def __init__(self, artifacts: list[object]) -> None:
        self._artifacts = artifacts

    def all(self) -> list[object]:
        return self._artifacts


@pytest.mark.asyncio
async def test_resolve_auto_smart_cut_rules_prefers_newest_edit_rules_from_recent_artifacts() -> None:
    class _FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
            return _FakeResult(
                [
                    Artifact(
                        job_id=uuid4(),
                        artifact_type="manual_editor_draft",
                        data_json={"smart_cut_rules": {"fillers": "um"}},
                    ),
                    Artifact(
                        job_id=uuid4(),
                        artifact_type="refine_decision_plan",
                        data_json={"smart_cut_rules": {"fillers": "uh"}},
                    ),
                ]
            )

    rules = await _resolve_auto_smart_cut_rules(_FakeSession(), job_id=uuid4(), content_profile=None)
    assert rules["fillers"] == "um"


@pytest.mark.asyncio
async def test_resolve_auto_smart_cut_rules_falls_back_to_content_profile() -> None:
    class _FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
            return _FakeResult([])

    content_profile = {"smart_cut_rules": {"fillers": "well"}}
    rules = await _resolve_auto_smart_cut_rules(_FakeSession(), job_id=uuid4(), content_profile=content_profile)
    assert rules["fillers"] == "well"


@pytest.mark.asyncio
async def test_resolve_auto_smart_cut_rules_skips_artifacts_without_explicit_rules() -> None:
    class _FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
            return _FakeResult(
                [
                    Artifact(
                        job_id=uuid4(),
                        artifact_type="manual_editor_draft",
                        data_json={},
                    ),
                    Artifact(
                        job_id=uuid4(),
                        artifact_type="refine_decision_plan",
                        data_json={"smart_cut_rules": {"fillers": "um"}},
                    ),
                ]
            )

    rules = await _resolve_auto_smart_cut_rules(_FakeSession(), job_id=uuid4(), content_profile={"smart_cut_rules": {"fillers": "well"}})
    assert rules["fillers"] == "um"


@pytest.mark.asyncio
async def test_resolve_auto_smart_cut_rules_defaults_when_no_artifact_or_profile_rules() -> None:
    class _FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
            return _FakeResult([])

    rules = await _resolve_auto_smart_cut_rules(_FakeSession(), job_id=uuid4(), content_profile=None)
    assert rules == default_smart_cut_rules_payload()
