from scripts import verify_manual_editor_apply_semantics as verify
from scripts.run_auto_edit_recovery_golden_set import GoldenJobCase


def test_default_apply_semantics_cases_only_selects_required_check_cases() -> None:
    cases = [
        GoldenJobCase(
            case_id="case-apply",
            scenario="manual apply",
            required_checks=["manual_editor_ready", "manual_editor_apply_semantics"],
            tags=["manual_editor"],
        ),
        GoldenJobCase(
            case_id="case-manual-only",
            scenario="manual only",
            required_checks=["manual_editor_ready", "subtitle_projection"],
            tags=["manual_editor"],
        ),
    ]

    selected = verify._default_apply_semantics_cases(cases)

    assert [case.case_id for case in selected] == ["case-apply"]


def test_run_cases_supports_direct_job_inspection(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_inspect(case, *, job_id="", source_name=""):
        captured["case_id"] = case.case_id
        captured["job_id"] = job_id
        captured["source_name"] = source_name
        return {
            "case_id": case.case_id,
            "job_id": job_id,
            "source_name": source_name,
            "managed_auto_cut_count": 0,
            "ok": True,
        }

    monkeypatch.setattr(verify, "inspect_manual_editor_apply_semantics", fake_inspect)

    results = verify.asyncio.run(
        verify._run_cases(
            [],
            explicit_job_id="job-123",
            explicit_source_name="demo.mp4",
        )
    )

    assert captured == {
        "case_id": "direct_job_inspection",
        "job_id": "job-123",
        "source_name": "demo.mp4",
    }
    assert results == [
        {
            "case_id": "direct_job_inspection",
            "job_id": "job-123",
            "source_name": "demo.mp4",
            "managed_auto_cut_count": 0,
            "ok": True,
        }
    ]
