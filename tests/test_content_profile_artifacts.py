from __future__ import annotations

import uuid
from types import SimpleNamespace

from roughcut.review.content_profile_artifacts import (
    build_content_profile_artifact_payloads,
    persist_content_profile_artifacts,
)


def test_build_content_profile_artifact_payloads_wraps_downstream_context_and_copies_inputs():
    draft_profile = {"subject_brand": "傲雷", "subject_model": "司令官2Ultra"}
    final_profile = {"review_mode": "auto_confirmed"}
    subtitle_quality_report = {"blocking": False, "score": 0.92}
    ocr_profile = {"visible_text": "傲雷 司令官2 Ultra"}

    payloads = build_content_profile_artifact_payloads(
        draft_profile=draft_profile,
        final_profile=final_profile,
        downstream_profile={**draft_profile, "review_mode": "manual_confirmed", "resolved_review_user_feedback": {}},
        subtitle_quality_report=subtitle_quality_report,
        ocr_profile=ocr_profile,
    )

    draft_profile["subject_brand"] = "别名"
    final_profile["review_mode"] = "pending"
    subtitle_quality_report["blocking"] = True
    ocr_profile["visible_text"] = "changed"

    assert payloads.draft_profile["subject_brand"] == "傲雷"
    assert payloads.final_profile["review_mode"] == "auto_confirmed"
    assert payloads.subtitle_quality_report["blocking"] is False
    assert payloads.ocr_profile["visible_text"] == "傲雷 司令官2 Ultra"
    assert payloads.downstream_context["resolved_profile"]["subject_brand"] == "傲雷"
    assert payloads.downstream_context["resolved_profile"]["review_mode"] == "manual_confirmed"


def test_persist_content_profile_artifacts_writes_expected_rows():
    job = SimpleNamespace(id=uuid.uuid4())
    step = SimpleNamespace(id=uuid.uuid4())
    review_step = SimpleNamespace(id=uuid.uuid4())

    class DummySession:
        def __init__(self) -> None:
            self.added = []

        def add(self, artifact) -> None:
            self.added.append(artifact)

    session = DummySession()

    persist_content_profile_artifacts(
        session,
        job=job,
        step=step,
        review_step=review_step,
        draft_profile={"subject_brand": "傲雷"},
        final_profile={"review_mode": "auto_confirmed"},
        downstream_profile={"subject_brand": "傲雷", "review_mode": "auto_confirmed"},
        subtitle_quality_report={"blocking": False, "score": 0.88},
        ocr_profile={"visible_text": "傲雷"},
    )

    artifact_types = [artifact.artifact_type for artifact in session.added]
    assert artifact_types == [
        "content_profile_ocr",
        "content_profile_draft",
        "subtitle_quality_report",
        "downstream_context",
        "content_profile_final",
    ]
    assert session.added[1].step_id == step.id
    assert session.added[4].step_id == review_step.id
    assert session.added[3].data_json["resolved_profile"]["subject_brand"] == "傲雷"
