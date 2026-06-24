import json
from pathlib import Path

from scripts import export_strategy_fixture_candidates as exporter


def _replay_context(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_path": "jobs/source.mp4",
        "workflow_template": "commentary_focus",
    }
    payload.update(overrides)
    return payload


def test_select_strategy_fixture_candidates_picks_best_candidate_per_strategy() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "demo low",
                "status": "failed",
                "artifact_type": "content_profile_draft",
                "strategy_type": "event_highlight",
                "classification": {"confidence": 0.4, "content_tags": ["gameplay"]},
                "pipeline_plan": {"enabled_features": ["highlight_window_selection"]},
                "replay_context": _replay_context(workflow_template="gameplay_highlight"),
            },
            {
                "job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "demo high",
                "status": "done",
                "artifact_type": "content_profile_final",
                "strategy_type": "event_highlight",
                "classification": {"confidence": 0.8, "content_tags": ["gameplay"]},
                "pipeline_plan": {
                    "enabled_features": ["highlight_window_selection", "local_audio_cues"],
                    "review_gates": ["highlight_review_recommended"],
                },
                "replay_context": _replay_context(workflow_template="gameplay_highlight"),
            },
        ],
        required_strategies=["event_highlight"],
    )

    selected = result["selected_candidates"]["event_highlight"]
    assert result["covered_strategy_types"] == ["event_highlight"]
    assert result["missing_strategy_types"] == []
    assert selected[0]["job_id"] == "22222222-2222-2222-2222-222222222222"
    assert selected[0]["golden_manifest_case"]["tags"] == [
        "strategy:event_highlight",
        "strategy_candidate",
        "artifact:content_profile_final",
    ]
    assert selected[0]["golden_manifest_case"]["enhancement_modes"] == []
    assert selected[0]["golden_manifest_case"]["required_checks"] == ["strategy_pipeline_coverage"]


def test_select_strategy_fixture_candidates_excludes_rejected_source_names() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "bad-tutorial.mp4",
                "artifact_type": "content_profile_final",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.95, "content_tags": ["tutorial"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
            },
            {
                "job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "bad-tutorial.mp4",
                "artifact_type": "content_profile_final",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.93, "content_tags": ["tutorial"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
            },
            {
                "job_id": "33333333-3333-3333-3333-333333333333",
                "source_name": "good-tutorial.mp4",
                "artifact_type": "content_profile_final",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.8, "content_tags": ["tutorial"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
            },
        ],
        required_strategies=["step_demonstration"],
        per_strategy=3,
        excluded_source_names={"bad-tutorial.mp4"},
    )

    assert result["excluded_candidate_count"] == 2
    assert result["manifest_ready_strategy_types"] == ["step_demonstration"]
    assert result["golden_manifest_jobs"][0]["reference_job_id"] == "33333333-3333-3333-3333-333333333333"


def test_collect_candidate_exclusions_from_reports_uses_reference_job_and_source() -> None:
    exclusions = exporter.collect_candidate_exclusions_from_reports(
        [
            {
                "golden_case_rows": [
                    {
                        "case_id": "case-a",
                        "reference_job_id": "11111111-1111-1111-1111-111111111111",
                        "evaluation_job_id": "22222222-2222-2222-2222-222222222222",
                        "source_name": "bad.mp4",
                        "status": "failed",
                        "tags": ["strategy:step_demonstration", "strategy_candidate"],
                    }
                ]
            }
        ]
    )

    assert exclusions == {
        "case_ids": {"case-a"},
        "job_ids": {
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        },
        "source_names": {"bad.mp4"},
    }


def test_select_strategy_fixture_candidates_reports_missing_required_strategy() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "strategy_type": "information_density",
                "classification": {"confidence": 0.9},
                "pipeline_plan": {},
                "replay_context": _replay_context(),
            }
        ],
        required_strategies=["information_density", "step_demonstration"],
    )

    assert result["covered_strategy_types"] == ["information_density"]
    assert result["missing_strategy_types"] == ["step_demonstration"]
    assert [case["risk_hints"] for case in result["golden_manifest_jobs"]] == [
        {"expected_strategy_type": "information_density"}
    ]


def test_select_strategy_fixture_candidates_prefers_replay_safe_candidate_before_score() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "cartoon-source.mp4",
                "status": "done",
                "artifact_type": "content_profile_final",
                "strategy_type": "experience_and_mood",
                "classification": {"confidence": 0.99},
                "pipeline_plan": {"enabled_features": ["mood_pacing", "ambient_preservation"]},
                "replay_context": _replay_context(workflow_template="commentary_focus"),
            },
            {
                "job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "travel-vlog.mp4",
                "status": "failed",
                "artifact_type": "content_profile_draft",
                "strategy_type": "experience_and_mood",
                "classification": {"confidence": 0.7, "content_tags": ["travel", "vlog"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="travel_vlog"),
            },
        ],
        required_strategies=["experience_and_mood"],
    )

    assert result["manifest_ready_strategy_types"] == ["experience_and_mood"]
    assert result["manifest_missing_strategy_types"] == []
    assert result["selected_candidates"]["experience_and_mood"][0]["job_id"] == "22222222-2222-2222-2222-222222222222"
    assert result["golden_manifest_jobs"][0]["reference_job_id"] == "22222222-2222-2222-2222-222222222222"


def test_narrative_candidate_manifest_case_uses_strategy_required_checks() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "watch_merge.mp4",
                "status": "done",
                "artifact_type": "downstream_context",
                "strategy_type": "narrative_assembly",
                "classification": {"confidence": 0.9, "content_tags": ["remix"]},
                "pipeline_plan": {"enabled_features": ["material_insert_plan"]},
                "replay_context": _replay_context(
                    workflow_template="multi_material_avatar_commentary",
                    enhancement_modes=["avatar_commentary"],
                    merged_source_names=["main.mp4", "detail.mp4", "broll.mp4"],
                    multi_material_ready=True,
                ),
            }
        ],
        required_strategies=["narrative_assembly"],
    )

    assert result["golden_manifest_jobs"][0]["required_checks"] == [
        "strategy_pipeline_coverage",
        "strategy_review_preview_evidence",
        "strategy_review_preview_media_evidence",
    ]


def test_normalize_strategy_fixture_candidate_carries_language_into_manifest_case() -> None:
    candidate = exporter.normalize_strategy_fixture_candidate(
        {
            "job_id": "11111111-1111-1111-1111-111111111111",
            "source_name": "tutorial.mp4",
            "strategy_type": "step_demonstration",
            "language": "en-US",
            "classification": {"confidence": 0.9},
            "pipeline_plan": {},
            "replay_context": _replay_context(workflow_template="tutorial_standard"),
        }
    )

    assert candidate is not None
    assert candidate["language"] == "en-US"
    assert candidate["golden_manifest_case"]["language"] == "en-US"


def test_looks_english_text_is_conservative() -> None:
    assert exporter._looks_english_text("Open the timeline, select the clip, and export the tutorial result.") is True
    assert exporter._looks_english_text("打开时间线 select the clip") is False
    assert exporter._looks_english_text("short text") is False


def test_select_strategy_fixture_candidates_dedupes_same_job_per_strategy() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "artifact_type": "content_profile_draft",
                "source_name": "中文素材.MOV",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.6},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
            },
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "artifact_type": "content_profile_final",
                "source_name": "中文素材.MOV",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.9},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
            },
        ],
        required_strategies=["step_demonstration"],
        per_strategy=2,
    )

    assert result["candidate_count"] == 1
    assert result["strategy_candidate_summary"]["step_demonstration"] == {
        "candidate_count": 1,
        "unique_reference_job_count": 1,
        "replay_safe_count": 1,
        "real_render_ready_count": 0,
        "top_reference_job_ids": ["11111111-1111-1111-1111-111111111111"],
        "statuses": {"unknown": 1},
        "artifact_types": {"content_profile_final": 1},
        "manifest_ready": True,
        "real_render_ready": False,
    }
    selected = result["selected_candidates"]["step_demonstration"][0]
    assert selected["artifact_type"] == "content_profile_final"
    assert selected["golden_manifest_case"]["case_id"] == "strategy_step_demonstration_mov_11111111"


def test_select_strategy_fixture_candidates_keeps_manifest_jobs_unique() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "strategy_type": "event_highlight",
                "classification": {"confidence": 0.9},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="gameplay_highlight"),
            },
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "strategy_type": "narrative_assembly",
                "classification": {"confidence": 0.9},
                "pipeline_plan": {},
                "replay_context": _replay_context(
                    workflow_template="gameplay_highlight",
                    enhancement_modes=["avatar_commentary"],
                    merged_source_names=["main.mp4", "detail.mp4", "broll.mp4"],
                    multi_material_ready=True,
                ),
            },
        ],
        required_strategies=["event_highlight", "narrative_assembly"],
    )

    assert result["covered_strategy_types"] == ["event_highlight", "narrative_assembly"]
    assert result["manifest_ready_strategy_types"] == ["event_highlight"]
    assert result["manifest_missing_strategy_types"] == ["narrative_assembly"]
    assert result["duplicate_reference_conflicts"] == [
        {
            "strategy_type": "narrative_assembly",
            "reference_job_id": "11111111-1111-1111-1111-111111111111",
            "case_id": "strategy_narrative_assembly_11111111",
        }
    ]
    assert len(result["golden_manifest_jobs"]) == 1
    assert result["strategy_candidate_summary"]["narrative_assembly"]["manifest_ready"] is False


def test_manifest_ready_skips_profile_only_narrative_candidate() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "profile-only.mp4",
                "strategy_type": "narrative_assembly",
                "classification": {"confidence": 0.9},
                "pipeline_plan": {"enabled_features": ["material_insert_plan"]},
                "local_asset_inventory": {"multi_material_ready": True},
                "replay_context": _replay_context(enhancement_modes=["avatar_commentary"]),
            }
        ],
        required_strategies=["narrative_assembly"],
    )

    assert result["covered_strategy_types"] == ["narrative_assembly"]
    assert result["manifest_ready_strategy_types"] == []
    assert result["manifest_missing_strategy_types"] == ["narrative_assembly"]
    assert result["replay_unsafe_candidates"] == [
        {
            "strategy_type": "narrative_assembly",
            "reference_job_id": "11111111-1111-1111-1111-111111111111",
            "case_id": "strategy_narrative_assembly_profile_only_mp4_11111111",
            "reason_codes": ["multi_material_replay_context_missing"],
        }
    ]
    assert result["strategy_candidate_summary"]["narrative_assembly"]["replay_safe_count"] == 0


def test_normalize_strategy_fixture_candidate_rejects_missing_job_id() -> None:
    assert exporter.normalize_strategy_fixture_candidate({"strategy_type": "event_highlight"}) is None


def test_select_strategy_fixture_candidates_reports_real_render_ready_candidate(tmp_path: Path) -> None:
    output_path = tmp_path / "rendered.mp4"
    output_path.write_bytes(b"video")

    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "highlight.mp4",
                "status": "done",
                "artifact_type": "content_profile_final",
                "strategy_type": "event_highlight",
                "classification": {"confidence": 0.8, "content_tags": ["gameplay"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="gameplay_highlight"),
                "real_render_context": {
                    "job_status": "done",
                    "outputs": [{"output_path": str(output_path), "status": "done", "exists": True}],
                },
            }
        ],
        required_strategies=["event_highlight"],
    )

    candidate = result["selected_candidates"]["event_highlight"][0]
    assert result["real_render_ready_strategy_types"] == ["event_highlight"]
    assert result["real_render_missing_strategy_types"] == []
    assert candidate["real_render_readiness"]["ready"] is True
    assert candidate["real_render_readiness"]["ready_output_count"] == 1
    assert result["strategy_candidate_summary"]["event_highlight"]["real_render_ready"] is True
    assert result["strategy_candidate_summary"]["event_highlight"]["real_render_ready_count"] == 1


def test_select_strategy_fixture_candidates_treats_done_render_output_as_ready_when_job_cancelled(tmp_path: Path) -> None:
    output_path = tmp_path / "rendered.mp4"
    output_path.write_bytes(b"video")

    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "tutorial.mp4",
                "status": "cancelled",
                "artifact_type": "content_profile_final",
                "strategy_type": "step_demonstration",
                "classification": {"confidence": 0.8, "content_tags": ["tutorial"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="tutorial_standard"),
                "real_render_context": {
                    "job_status": "cancelled",
                    "outputs": [{"output_path": str(output_path), "status": "done", "exists": True}],
                },
            }
        ],
        required_strategies=["step_demonstration"],
    )

    candidate = result["selected_candidates"]["step_demonstration"][0]
    assert result["real_render_ready_strategy_types"] == ["step_demonstration"]
    assert candidate["real_render_readiness"]["ready"] is True
    assert candidate["real_render_readiness"]["reason_codes"] == ["job_status_not_terminal=cancelled"]


def test_select_strategy_fixture_candidates_keeps_real_render_gap_separate_from_manifest_readiness() -> None:
    result = exporter.select_strategy_fixture_candidates(
        [
            {
                "job_id": "11111111-1111-1111-1111-111111111111",
                "source_name": "highlight.mp4",
                "status": "done",
                "artifact_type": "content_profile_final",
                "strategy_type": "event_highlight",
                "classification": {"confidence": 0.8, "content_tags": ["gameplay"]},
                "pipeline_plan": {},
                "replay_context": _replay_context(workflow_template="gameplay_highlight"),
                "real_render_context": {
                    "job_status": "done",
                    "outputs": [{"output_path": "missing.mp4", "status": "done", "exists": False}],
                },
            }
        ],
        required_strategies=["event_highlight"],
    )

    assert result["manifest_ready_strategy_types"] == ["event_highlight"]
    assert result["real_render_ready_strategy_types"] == []
    assert result["real_render_missing_strategy_types"] == ["event_highlight"]
    assert result["selected_candidates"]["event_highlight"][0]["real_render_readiness"] == {
        "ready": False,
        "reason_codes": ["render_output_not_ready"],
        "output_count": 1,
        "ready_output_count": 0,
        "output_paths": [],
    }


def test_main_fails_when_manifest_ready_set_is_incomplete(monkeypatch, capsys) -> None:
    async def fake_export(**_: object) -> dict[str, object]:
        return {
            "schema": exporter.STRATEGY_FIXTURE_CANDIDATES_SCHEMA,
            "missing_strategy_types": [],
            "manifest_missing_strategy_types": ["narrative_assembly"],
        }

    monkeypatch.setattr(exporter, "export_strategy_fixture_candidates_from_db", fake_export)
    monkeypatch.setattr("sys.argv", ["export_strategy_fixture_candidates.py"])

    assert exporter.main() == 1
    assert json.loads(capsys.readouterr().out)["manifest_missing_strategy_types"] == ["narrative_assembly"]


def test_main_allows_candidate_only_mode(monkeypatch) -> None:
    async def fake_export(**_: object) -> dict[str, object]:
        return {
            "schema": exporter.STRATEGY_FIXTURE_CANDIDATES_SCHEMA,
            "missing_strategy_types": [],
            "manifest_missing_strategy_types": ["narrative_assembly"],
        }

    monkeypatch.setattr(exporter, "export_strategy_fixture_candidates_from_db", fake_export)
    monkeypatch.setattr("sys.argv", ["export_strategy_fixture_candidates.py", "--allow-candidate-only"])

    assert exporter.main() == 0


def test_main_can_require_real_render_ready(monkeypatch) -> None:
    async def fake_export(**_: object) -> dict[str, object]:
        return {
            "schema": exporter.STRATEGY_FIXTURE_CANDIDATES_SCHEMA,
            "missing_strategy_types": [],
            "manifest_missing_strategy_types": [],
            "real_render_missing_strategy_types": ["event_highlight"],
        }

    monkeypatch.setattr(exporter, "export_strategy_fixture_candidates_from_db", fake_export)
    monkeypatch.setattr("sys.argv", ["export_strategy_fixture_candidates.py", "--require-real-render-ready"])

    assert exporter.main() == 1


def test_main_can_write_candidate_golden_manifest(monkeypatch, tmp_path: Path) -> None:
    async def fake_export(**_: object) -> dict[str, object]:
        return {
            "schema": exporter.STRATEGY_FIXTURE_CANDIDATES_SCHEMA,
            "required_strategy_types": ["event_highlight"],
            "manifest_ready_strategy_types": ["event_highlight"],
            "real_render_ready_strategy_types": [],
            "missing_strategy_types": [],
            "manifest_missing_strategy_types": [],
            "golden_manifest_jobs": [
                {
                    "case_id": "strategy_event_highlight_demo",
                    "enhancement_modes": [],
                    "reference_job_id": "11111111-1111-1111-1111-111111111111",
                    "required_checks": ["strategy_pipeline_coverage"],
                    "tags": ["strategy:event_highlight", "strategy_candidate"],
                }
            ],
        }

    output = tmp_path / "candidates.json"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(exporter, "export_strategy_fixture_candidates_from_db", fake_export)
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_strategy_fixture_candidates.py",
            "--output",
            str(output),
            "--manifest-output",
            str(manifest),
        ],
    )

    assert exporter.main() == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema"] == exporter.STRATEGY_CANDIDATE_MANIFEST_SCHEMA
    assert payload["required_strategy_types"] == ["event_highlight"]
    assert payload["manifest_ready_strategy_types"] == ["event_highlight"]
    assert payload["jobs"] == [
        {
            "case_id": "strategy_event_highlight_demo",
            "enhancement_modes": [],
            "reference_job_id": "11111111-1111-1111-1111-111111111111",
            "required_checks": ["strategy_pipeline_coverage"],
            "tags": ["strategy:event_highlight", "strategy_candidate"],
        }
    ]
