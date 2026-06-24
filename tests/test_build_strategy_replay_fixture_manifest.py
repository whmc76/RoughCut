from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import build_strategy_replay_fixture_manifest as builder
from scripts import run_auto_edit_recovery_golden_set as golden
from scripts.verify_strategy_fixture_coverage import verify_strategy_fixture_coverage
from roughcut.edit.strategy_profile import infer_strategy_type


def test_build_strategy_replay_fixture_manifest_declares_all_strategy_cases(tmp_path: Path) -> None:
    payload = builder.build_strategy_replay_fixture_manifest(tmp_path / "fixtures")

    assert payload["schema"] == builder.STRATEGY_REPLAY_FIXTURE_SCHEMA
    jobs = payload["jobs"]
    assert [job["case_id"] for job in jobs] == [
        "strategy_information_density_generated_commentary",
        "strategy_step_demonstration_generated_tutorial",
        "strategy_experience_and_mood_generated_vlog",
        "strategy_event_highlight_generated_gameplay",
        "strategy_narrative_assembly_generated_multimaterial",
    ]
    assert [job["required_checks"] for job in jobs] == [
        ["strategy_pipeline_coverage"],
        ["strategy_pipeline_coverage"],
        ["strategy_pipeline_coverage"],
        ["strategy_pipeline_coverage"],
        [
            "strategy_pipeline_coverage",
            "strategy_review_preview_evidence",
            "strategy_review_preview_media_evidence",
        ],
    ]
    assert [len(job["transcript_segments"]) for job in jobs] == [1, 1, 1, 2, 1]
    assert [job["risk_hints"]["expected_strategy_type"] for job in jobs] == [
        "information_density",
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    ]

    information = jobs[0]
    assert information["tags"] == [
        "strategy:information_density",
        "strategy_fixture",
        "generated_fixture",
        "replay_safe",
    ]
    assert information["product_controls"]["edit_mode"] == "talking_head"
    assert information["strategy_classification"]["editing_signals"] == [
        "retake_likely",
        "silence_trim_useful",
        "subtitle_important",
    ]
    assert Path(information["source_path"]).is_absolute()

    step = jobs[1]
    assert step["tags"] == [
        "strategy:step_demonstration",
        "strategy_fixture",
        "generated_fixture",
        "replay_safe",
    ]
    assert step["product_controls"]["edit_mode"] == "tutorial"
    assert step["strategy_classification"]["media_tags"] == ["screen_recording", "operation_demo"]
    assert Path(step["source_path"]).is_absolute()

    experience = jobs[2]
    assert experience["tags"] == [
        "strategy:experience_and_mood",
        "strategy_fixture",
        "generated_fixture",
        "replay_safe",
    ]
    assert experience["product_controls"]["edit_mode"] == "vlog"
    assert experience["strategy_classification"]["content_tags"] == ["vlog", "travel", "experience"]
    assert Path(experience["source_path"]).is_absolute()

    event = jobs[3]
    assert event["tags"] == [
        "strategy:event_highlight",
        "strategy_fixture",
        "generated_fixture",
        "replay_safe",
    ]
    assert event["product_controls"]["edit_mode"] == "highlight"
    assert event["strategy_classification"]["content_tags"] == ["gameplay", "highlight", "event_highlight"]
    assert Path(event["source_path"]).is_absolute()

    narrative = jobs[4]
    assert narrative["tags"] == [
        "strategy:narrative_assembly",
        "strategy_fixture",
        "generated_fixture",
        "replay_safe",
    ]
    assert narrative["product_controls"] == {
        "edit_mode": "multi_material",
        "automation_level": "standard",
        "material_usage": "all_uploaded",
    }
    assert narrative["strategy_classification"]["asset_tags"] == [
        "multi_material_ready",
        "visual_inserts_available",
    ]
    assert len(narrative["source_paths"]) == 3
    assert all(Path(path).is_absolute() for path in narrative["source_paths"])


def test_write_manifest_only_output_loads_in_golden_runner(tmp_path: Path) -> None:
    manifest_path = builder.write_strategy_replay_fixture_manifest(
        tmp_path / "fixtures",
        generate_media=False,
    )

    cases = golden.load_golden_job_manifest(manifest_path)

    assert [case.case_id for case in cases] == [
        "strategy_information_density_generated_commentary",
        "strategy_step_demonstration_generated_tutorial",
        "strategy_experience_and_mood_generated_vlog",
        "strategy_event_highlight_generated_gameplay",
        "strategy_narrative_assembly_generated_multimaterial",
    ]
    assert cases[0].source_path.endswith("information_density_talking_head_commentary.mp4")
    assert cases[0].strategy_classification["primary_type"] == "talking_head"
    assert cases[1].source_path.endswith("step_demonstration_screen_tutorial.mp4")
    assert cases[2].source_path.endswith("experience_mood_travel_market_vlog.mp4")
    assert cases[3].source_path.endswith("event_highlight_gameplay_action_peak.mp4")
    assert cases[4].source_paths[0].endswith("narrative_anchor_avatar_commentary.mp4")
    assert cases[4].product_controls["edit_mode"] == "multi_material"


def test_render_required_checks_only_attach_to_event_highlight_fixture(tmp_path: Path) -> None:
    manifest_path = builder.write_strategy_replay_fixture_manifest(
        tmp_path / "fixtures",
        generate_media=False,
        include_render_required_checks=True,
    )

    cases = golden.load_golden_job_manifest(manifest_path)
    checks_by_case = {case.case_id: case.required_checks for case in cases}

    assert checks_by_case["strategy_event_highlight_generated_gameplay"] == [
        "strategy_pipeline_coverage",
        "strategy_boundary_samples",
    ]
    assert checks_by_case["strategy_information_density_generated_commentary"] == [
        "strategy_pipeline_coverage"
    ]
    assert checks_by_case["strategy_step_demonstration_generated_tutorial"] == [
        "strategy_pipeline_coverage"
    ]
    assert checks_by_case["strategy_experience_and_mood_generated_vlog"] == [
        "strategy_pipeline_coverage"
    ]
    assert checks_by_case["strategy_narrative_assembly_generated_multimaterial"] == [
        "strategy_pipeline_coverage",
        "strategy_review_preview_evidence",
        "strategy_review_preview_media_evidence",
    ]


def test_strategy_render_required_checks_are_strategy_configured() -> None:
    assert set(builder.STRATEGY_CONTENT_REQUIRED_CHECKS) == {
        "information_density",
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    }
    assert set(builder.STRATEGY_RENDER_REQUIRED_CHECKS) == {
        "information_density",
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    }
    assert builder.strategy_required_checks("event_highlight", include_render_required_checks=True) == [
        "strategy_pipeline_coverage",
        "strategy_boundary_samples",
    ]
    assert builder.strategy_required_checks("narrative_assembly", include_render_required_checks=True) == [
        "strategy_pipeline_coverage",
        "strategy_review_preview_evidence",
        "strategy_review_preview_media_evidence",
    ]
    assert builder.strategy_required_checks("step_demonstration", include_render_required_checks=True) == [
        "strategy_pipeline_coverage"
    ]
    assert builder.strategy_required_checks("event_highlight", include_render_required_checks=False) == [
        "strategy_pipeline_coverage"
    ]


def test_generated_manifest_strategy_context_resolves_expected_strategy(tmp_path: Path) -> None:
    payload = builder.build_strategy_replay_fixture_manifest(tmp_path / "fixtures")

    for job in payload["jobs"]:
        expected = job["risk_hints"]["expected_strategy_type"]
        content_profile = {
            "source_context": {
                "strategy_classification": job["strategy_classification"],
                "product_controls": job["product_controls"],
            }
        }

        assert infer_strategy_type(
            workflow_template=job["workflow_template"],
            content_profile=content_profile,
        ) == expected


def test_generated_manifest_declares_full_strategy_coverage_contract(tmp_path: Path) -> None:
    payload = builder.build_strategy_replay_fixture_manifest(tmp_path / "fixtures")
    batch_report = {
        "golden_case_rows": [
            {
                "case_id": job["case_id"],
                "tags": job["tags"],
                "risk_hints": job["risk_hints"],
                "required_check_statuses": {
                    "strategy_pipeline_coverage": {
                        "passed": True,
                        "expected_strategy_types": [job["risk_hints"]["expected_strategy_type"]],
                        "observed_strategy_types": [job["risk_hints"]["expected_strategy_type"]],
                        "missing_strategy_types": [],
                    }
                },
            }
            for job in payload["jobs"]
        ]
    }

    result = verify_strategy_fixture_coverage(batch_report)

    assert result["ok"] is True
    assert result["covered_strategy_types"] == [
        "event_highlight",
        "experience_and_mood",
        "information_density",
        "narrative_assembly",
        "step_demonstration",
    ]
    assert result["missing_strategy_types"] == []


def test_generate_strategy_replay_fixture_media_uses_deterministic_ffmpeg_commands(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    generated = builder.generate_strategy_replay_fixture_media(
        tmp_path / "fixtures",
        force=True,
        ffmpeg_bin="ffmpeg-test",
    )

    assert len(generated) == 7
    assert len(calls) == 7
    assert {Path(cmd[-1]).name for cmd in calls} == {
        "information_density_talking_head_commentary.mp4",
        "step_demonstration_screen_tutorial.mp4",
        "experience_mood_travel_market_vlog.mp4",
        "event_highlight_gameplay_action_peak.mp4",
        "narrative_anchor_avatar_commentary.mp4",
        "narrative_detail_insert_material.mp4",
        "narrative_broll_storybeat.mp4",
    }
    for cmd in calls:
        assert cmd[0] == "ffmpeg-test"
        assert cmd[cmd.index("-f") + 1] == "lavfi"
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-c:a" in cmd
        assert "aac" in cmd


def test_generate_strategy_replay_fixture_media_skips_existing_files(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "fixtures"
    for spec in builder.strategy_replay_fixture_media_specs(output_dir):
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        spec.path.write_bytes(b"existing mp4")

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("ffmpeg should not be invoked for existing media")

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    assert builder.generate_strategy_replay_fixture_media(output_dir, ffmpeg_bin="ffmpeg-test") == []
