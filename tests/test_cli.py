from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import roughcut.cli as cli_mod
from roughcut.cli import QualityAuditRow


def test_init_creates_project_dirs_and_env(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    (tmp_path / ".env.example").write_text("OUTPUT_DIR=output\n", encoding="utf-8")
    output_root = Path("F:/roughcut_outputs/tests") / f"cli-init-{tmp_path.name}"
    debug_root = output_root / "render-debug"
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(output_root), render_debug_dir=str(debug_root)),
    )

    result = runner.invoke(cli_mod.cli, ["init"])

    assert result.exit_code == 0
    assert output_root.exists()
    assert debug_root.exists()
    assert (tmp_path / "watch").exists()
    assert (tmp_path / ".env").exists()


def test_doctor_reports_missing_ffmpeg_as_failure(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    output_root = Path("F:/roughcut_outputs/tests") / f"cli-doctor-{tmp_path.name}"
    debug_root = output_root / "render-debug"
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(output_root), render_debug_dir=str(debug_root)),
    )

    def fake_which(name: str) -> str | None:
        if name in {"ffmpeg", "ffprobe"}:
            return None
        if name == "uv":
            return "C:/tools/uv.exe"
        return None

    monkeypatch.setattr(cli_mod.shutil, "which", fake_which)

    result = runner.invoke(cli_mod.cli, ["doctor"])

    assert result.exit_code == 1
    assert "ffmpeg" in result.output


def test_quality_audit_prints_sorted_rows(monkeypatch):
    runner = CliRunner()

    async def fake_quality_audit_async(*, limit: int, statuses: list[str], persist: bool):
        assert limit == 2
        assert statuses == ["done"]
        assert persist is False
        return [
            QualityAuditRow(
                job_id="job-1",
                source_name="a.mp4",
                status="done",
                score=52.0,
                grade="D",
                issue_codes=["detail_blind"],
                recommended_rerun_steps=["content_profile", "render"],
            ),
            QualityAuditRow(
                job_id="job-2",
                source_name="b.mp4",
                status="done",
                score=74.0,
                grade="C",
                issue_codes=["subtitle_sync_issue"],
                recommended_rerun_steps=["render", "platform_package"],
            ),
        ]

    monkeypatch.setattr(cli_mod, "_quality_audit_async", fake_quality_audit_async)

    result = runner.invoke(cli_mod.cli, ["quality", "audit", "--limit", "2", "--status", "done"])

    assert result.exit_code == 0
    assert "52.0 D done" in result.output
    assert "issues=detail_blind" in result.output
    assert "rerun=content_profile, render" in result.output


def test_quality_improve_outputs_processed_summary(monkeypatch):
    runner = CliRunner()

    async def fake_quality_improve_async(
        *,
        limit: int,
        max_score: float,
        statuses: list[str],
        max_processing: int,
        dry_run: bool,
    ):
        assert limit == 1
        assert max_score == 74.9
        assert statuses == ["done"]
        assert max_processing == 6
        assert dry_run is False
        return {
            "processed_count": 1,
            "eligible_count": 3,
            "total_scanned": 8,
            "processing_count": 2,
            "available_slots": 4,
            "jobs": [
                {
                    "job_id": "job-1",
                    "source_name": "a.mp4",
                    "status": "done",
                    "score": 52.0,
                    "grade": "D",
                    "issue_codes": ["detail_blind"],
                    "recommended_rerun_steps": ["content_profile", "render"],
                    "action": "triggered",
                }
            ],
        }

    monkeypatch.setattr(cli_mod, "_quality_improve_async", fake_quality_improve_async)

    result = runner.invoke(cli_mod.cli, ["quality", "improve", "--limit", "1", "--status", "done"])

    assert result.exit_code == 0
    assert "triggered  52.0 D done" in result.output
    assert "processed=1" in result.output
    assert "processing_now=2" in result.output
    assert "available_slots=4" in result.output


def test_telegram_agent_command_runs_service(monkeypatch):
    runner = CliRunner()
    called = {"run_forever": False}

    class FakeService:
        async def run_forever(self):
            called["run_forever"] = True

    import roughcut.review.telegram_bot as telegram_bot_mod

    monkeypatch.setattr(telegram_bot_mod, "get_telegram_review_bot_service", lambda: FakeService())

    result = runner.invoke(cli_mod.cli, ["telegram-agent"])

    assert result.exit_code == 0
    assert "Starting Telegram agent" in result.output
    assert called["run_forever"] is True


def test_review_notifications_command_lists_snapshot_json(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    monkeypatch.setattr(
        review_notification_mod,
        "build_review_notification_snapshot",
        lambda statuses=None, job_id=None, kind=None, limit=20: {
            "state_dir": "F:/roughcut_outputs/telegram-agent",
            "store_file": "F:/roughcut_outputs/telegram-agent/review_notifications.json",
            "detail": "2 queued notifications",
            "summary": {"total": 2, "pending": 1, "due_now": 1, "failed": 0, "delivered": 1},
            "items": [
                {
                    "notification_id": "n-1",
                    "kind": "content_profile",
                    "job_id": "job-1",
                    "status": "pending",
                    "attempt_count": 2,
                    "next_attempt_at": "2026-04-17T00:00:00+00:00",
                    "last_error": "network down",
                    "force_full_review": False,
                    "updated_at": "2026-04-17T00:00:00+00:00",
                }
            ],
        },
    )

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--json-output"])

    assert result.exit_code == 0
    assert '"total": 2' in result.output
    assert '"notification_id": "n-1"' in result.output


def test_review_notifications_command_passes_status_filters_to_snapshot(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    observed: dict[str, object] = {}

    def fake_snapshot(*, statuses=None, job_id=None, kind=None, limit=20):
        observed["statuses"] = statuses
        observed["job_id"] = job_id
        observed["kind"] = kind
        observed["limit"] = limit
        return {
            "state_dir": "F:/roughcut_outputs/telegram-agent",
            "store_file": "F:/roughcut_outputs/telegram-agent/review_notifications.json",
            "detail": "1 queued notifications",
            "summary": {"total": 1, "pending": 0, "due_now": 0, "failed": 1, "delivered": 0},
            "items": [
                {
                    "notification_id": "n-2",
                    "kind": "final_review",
                    "job_id": "job-2",
                    "status": "failed",
                    "attempt_count": 3,
                    "next_attempt_at": "2026-04-17T00:00:00+00:00",
                    "last_error": "network down",
                    "force_full_review": False,
                    "updated_at": "2026-04-17T00:00:00+00:00",
                }
            ],
        }

    monkeypatch.setattr(review_notification_mod, "build_review_notification_snapshot", fake_snapshot)

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--status", "failed"])

    assert result.exit_code == 0
    assert observed == {"statuses": ["failed"], "job_id": None, "kind": None, "limit": 20}
    assert "total=1 pending=0 due_now=0 failed=1 delivered=0" in result.output
    assert "detail=1 queued notifications" in result.output


def test_review_notifications_command_passes_job_id_filter_to_snapshot(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    observed: dict[str, object] = {}

    def fake_snapshot(*, statuses=None, job_id=None, kind=None, limit=20):
        observed.update({"statuses": statuses, "job_id": job_id, "kind": kind, "limit": limit})
        return {
            "state_dir": "F:/roughcut_outputs/telegram-agent",
            "store_file": "F:/roughcut_outputs/telegram-agent/review_notifications.json",
            "detail": "1 queued notifications",
            "summary": {"total": 1, "pending": 1, "due_now": 0, "failed": 0, "delivered": 0},
            "items": [],
        }

    monkeypatch.setattr(review_notification_mod, "build_review_notification_snapshot", fake_snapshot)

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--job-id", "job-1"])

    assert result.exit_code == 0
    assert observed == {"statuses": None, "job_id": "job-1", "kind": None, "limit": 20}


def test_review_notifications_command_requeues_one_item(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    monkeypatch.setattr(
        review_notification_mod,
        "requeue_review_notification",
        lambda notification_id: SimpleNamespace(
            notification_id=notification_id,
            notification_key="content_profile:job-1:0",
            kind="content_profile",
            job_id="job-1",
            force_full_review=False,
            status="pending",
            created_at="2026-04-17T00:00:00+00:00",
            updated_at="2026-04-17T00:00:01+00:00",
            next_attempt_at="2026-04-17T00:00:01+00:00",
            attempt_count=0,
            last_error="",
            delivered_at="",
        ),
    )

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--requeue", "n-1"])

    assert result.exit_code == 0
    assert "requeued n-1" in result.output


def test_review_notifications_command_drops_one_item(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    monkeypatch.setattr(review_notification_mod, "drop_review_notification", lambda notification_id: notification_id == "n-1")

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--drop", "n-1"])

    assert result.exit_code == 0
    assert "dropped n-1" in result.output


def test_review_notifications_command_reports_store_errors(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    monkeypatch.setattr(
        review_notification_mod,
        "requeue_review_notification",
        lambda notification_id: (_ for _ in ()).throw(RuntimeError("Review notification store is unreadable")),
    )

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--requeue", "n-1"])

    assert result.exit_code != 0
    assert "Review notification store is unreadable" in result.output


def test_review_notifications_command_requeues_filtered_items(monkeypatch):
    runner = CliRunner()
    import roughcut.telegram.review_notification_service as review_notification_mod

    monkeypatch.setattr(
        review_notification_mod,
        "list_review_notifications",
        lambda statuses=None, job_id=None, kind=None, limit=None: [
            SimpleNamespace(notification_id="n-1"),
            SimpleNamespace(notification_id="n-2"),
        ],
    )
    monkeypatch.setattr(
        review_notification_mod,
        "requeue_review_notifications",
        lambda notification_ids: [SimpleNamespace(notification_id=item) for item in notification_ids],
    )

    result = runner.invoke(cli_mod.cli, ["review-notifications", "--job-id", "job-1", "--requeue-filtered"])

    assert result.exit_code == 0
    assert "requeued 2 notifications job=job-1" in result.output


def test_quality_live_readiness_prints_text_summary(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        cli_mod,
        "load_live_readiness_snapshot",
        lambda report_path=None: {
            "status": "fail",
            "gate_passed": False,
            "summary": "未满足 live dry run 准入门槛",
            "stable_run_count": 2,
            "required_stable_runs": 3,
            "golden_job_count": 4,
            "evaluated_job_count": 4,
            "failure_reasons": ["连续稳定批次不足：2/3", "P0 blocker 未清零：1 个"],
            "warning_reasons": ["未显式提供 golden jobs，当前按本次 batch 全量样本评估"],
            "report_file": "E:/WorkSpace/RoughCut/output/test/fullchain-batch/batch_report.json",
            "report_created_at": "2026-04-17T00:00:00+00:00",
            "detail": "",
        },
    )

    result = runner.invoke(cli_mod.cli, ["quality", "live-readiness"])

    assert result.exit_code == 0
    assert "status=fail gate_passed=false stable_runs=2/3" in result.output
    assert "summary=未满足 live dry run 准入门槛" in result.output
    assert "golden_jobs=4 evaluated_jobs=4" in result.output
    assert "failures=连续稳定批次不足：2/3 / P0 blocker 未清零：1 个" in result.output


def test_quality_live_readiness_prints_json_and_passes_report_path(monkeypatch):
    runner = CliRunner()
    observed: dict[str, object] = {}

    def fake_snapshot(report_path=None):
        observed["report_path"] = report_path
        return {
            "status": "pass",
            "gate_passed": True,
            "summary": "满足 live dry run 准入门槛",
            "stable_run_count": 3,
            "required_stable_runs": 3,
            "failure_reasons": [],
            "warning_reasons": [],
            "report_file": str(report_path),
            "detail": "",
        }

    monkeypatch.setattr(cli_mod, "load_live_readiness_snapshot", fake_snapshot)

    result = runner.invoke(
        cli_mod.cli,
        ["quality", "live-readiness", "--report-path", "E:/tmp/batch_report.json", "--json-output"],
    )

    assert result.exit_code == 0
    assert observed == {"report_path": "E:/tmp/batch_report.json"}
    assert '"status": "pass"' in result.output
    assert '"report_path_input": "E:/tmp/batch_report.json"' in result.output


def test_quality_live_readiness_reports_loader_errors(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        cli_mod,
        "load_live_readiness_snapshot",
        lambda report_path=None: (_ for _ in ()).throw(RuntimeError("cannot read batch report")),
    )

    result = runner.invoke(cli_mod.cli, ["quality", "live-readiness"])

    assert result.exit_code != 0
    assert "cannot read batch report" in result.output


def test_quality_live_readiness_require_pass_fails_when_gate_not_passed(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        cli_mod,
        "load_live_readiness_snapshot",
        lambda report_path=None: {
            "status": "fail",
            "gate_passed": False,
            "summary": "未满足 live dry run 准入门槛",
            "stable_run_count": 2,
            "required_stable_runs": 3,
            "failure_reasons": ["连续稳定批次不足：2/3"],
            "warning_reasons": [],
            "report_file": "E:/WorkSpace/RoughCut/output/test/fullchain-batch/batch_report.json",
            "detail": "",
        },
    )

    result = runner.invoke(cli_mod.cli, ["quality", "live-readiness", "--require-pass"])

    assert result.exit_code == 1
    assert "status=fail gate_passed=false stable_runs=2/3" in result.output


def test_quality_live_readiness_require_pass_succeeds_when_gate_passes(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(
        cli_mod,
        "load_live_readiness_snapshot",
        lambda report_path=None: {
            "status": "pass",
            "gate_passed": True,
            "summary": "满足 live dry run 准入门槛",
            "stable_run_count": 3,
            "required_stable_runs": 3,
            "failure_reasons": [],
            "warning_reasons": [],
            "report_file": "E:/WorkSpace/RoughCut/output/test/fullchain-batch/batch_report.json",
            "detail": "",
        },
    )

    result = runner.invoke(cli_mod.cli, ["quality", "live-readiness", "--require-pass"])

    assert result.exit_code == 0
    assert "status=pass gate_passed=true stable_runs=3/3" in result.output


def test_clip_test_runs_manual_pipeline(monkeypatch, tmp_path: Path):
    runner = CliRunner()
    source = tmp_path / "demo.mp4"
    source.write_bytes(b"video")
    called: dict[str, object] = {}

    async def fake_run_manual_clip_test(
        source_path: Path,
        *,
        language: str,
        channel_profile: str | None,
        sample_seconds: int,
    ):
        called["source"] = source_path
        called["language"] = language
        called["channel_profile"] = channel_profile
        called["sample_seconds"] = sample_seconds
        return {
            "source": str(source_path),
            "language": language,
            "channel_profile": channel_profile,
            "sample_seconds": sample_seconds,
        }

    import roughcut.testing.manual_clip as manual_clip_mod

    monkeypatch.setattr(manual_clip_mod, "run_manual_clip_test", fake_run_manual_clip_test)

    result = runner.invoke(
        cli_mod.cli,
        [
            "clip-test",
            str(source),
            "--language",
            "zh-CN",
            "--channel-profile",
            "edc_tactical",
            "--sample-seconds",
            "45",
        ],
    )

    assert result.exit_code == 0
    assert called == {
        "source": source,
        "language": "zh-CN",
        "channel_profile": "edc_tactical",
        "sample_seconds": 45,
    }
    assert "Running clip test for:" in result.output
    assert '"sample_seconds": 45' in result.output


def test_quality_improve_continues_past_skipped_jobs(monkeypatch):
    runner = CliRunner()
    jobs = [
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000001"), steps=[], artifacts=[]),
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000002"), steps=[], artifacts=[]),
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000003"), steps=[], artifacts=[]),
    ]

    async def fake_quality_audit_async(*, limit: int, statuses: list[str], persist: bool):
        return [
            QualityAuditRow("00000000-0000-0000-0000-000000000001", "a.mp4", "done", 52.0, "D", ["detail_blind"], ["content_profile"]),
            QualityAuditRow("00000000-0000-0000-0000-000000000002", "b.mp4", "done", 58.0, "D", ["detail_blind"], ["content_profile"]),
            QualityAuditRow("00000000-0000-0000-0000-000000000003", "c.mp4", "done", 64.0, "C", ["detail_blind"], ["content_profile"]),
        ]

    class FakeResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return list(self._items)

    class FakeScalarResult:
        def scalar_one(self):
            return 0

    class FakeSession:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeScalarResult()
            return FakeResult(jobs)

        async def commit(self):
            return None

    triggered_ids: list[str] = []

    async def fake_assess_and_maybe_rerun_job(session, job, steps):
        triggered_ids.append(str(job.id))
        return str(job.id).endswith("3")

    monkeypatch.setattr(cli_mod, "_quality_audit_async", fake_quality_audit_async)

    import roughcut.db.session as db_session_mod
    import roughcut.pipeline.orchestrator as orchestrator_mod

    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(orchestrator_mod, "_assess_and_maybe_rerun_job", fake_assess_and_maybe_rerun_job)

    result = runner.invoke(cli_mod.cli, ["quality", "improve", "--limit", "1", "--status", "done"])

    assert result.exit_code == 0
    assert triggered_ids == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
    assert "c.mp4" in result.output


def test_quality_improve_skips_when_processing_queue_is_full(monkeypatch):
    runner = CliRunner()

    async def fake_quality_audit_async(*, limit: int, statuses: list[str], persist: bool):
        return [
            QualityAuditRow("00000000-0000-0000-0000-000000000001", "a.mp4", "done", 52.0, "D", ["detail_blind"], ["content_profile"])
        ]

    class FakeScalarResult:
        def scalar_one(self):
            return 6

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            return FakeScalarResult()

    monkeypatch.setattr(cli_mod, "_quality_audit_async", fake_quality_audit_async)

    import roughcut.db.session as db_session_mod

    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: (lambda: FakeSession()))

    result = runner.invoke(cli_mod.cli, ["quality", "improve", "--limit", "2", "--status", "done"])

    assert result.exit_code == 0
    assert "processed=0" in result.output
    assert "processing_now=6" in result.output
    assert "available_slots=0" in result.output


def test_quality_improve_respects_available_slots(monkeypatch):
    runner = CliRunner()
    jobs = [
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000001"), steps=[], artifacts=[]),
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000002"), steps=[], artifacts=[]),
        SimpleNamespace(id=cli_mod.uuid.UUID("00000000-0000-0000-0000-000000000003"), steps=[], artifacts=[]),
    ]

    async def fake_quality_audit_async(*, limit: int, statuses: list[str], persist: bool):
        return [
            QualityAuditRow("00000000-0000-0000-0000-000000000001", "a.mp4", "done", 52.0, "D", ["detail_blind"], ["content_profile"]),
            QualityAuditRow("00000000-0000-0000-0000-000000000002", "b.mp4", "done", 58.0, "D", ["detail_blind"], ["content_profile"]),
            QualityAuditRow("00000000-0000-0000-0000-000000000003", "c.mp4", "done", 64.0, "C", ["detail_blind"], ["content_profile"]),
        ]

    class FakeScalarResult:
        def scalar_one(self):
            return 5

    class FakeRowsResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return list(self._items)

    class FakeSession:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeScalarResult()
            return FakeRowsResult(jobs)

        async def commit(self):
            return None

    triggered_ids: list[str] = []

    async def fake_assess_and_maybe_rerun_job(session, job, steps):
        triggered_ids.append(str(job.id))
        return True

    monkeypatch.setattr(cli_mod, "_quality_audit_async", fake_quality_audit_async)

    import roughcut.db.session as db_session_mod
    import roughcut.pipeline.orchestrator as orchestrator_mod

    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(orchestrator_mod, "_assess_and_maybe_rerun_job", fake_assess_and_maybe_rerun_job)

    result = runner.invoke(cli_mod.cli, ["quality", "improve", "--limit", "3", "--status", "done"])

    assert result.exit_code == 0
    assert triggered_ids == [
        "00000000-0000-0000-0000-000000000001",
    ]
    assert "processed=1" in result.output
    assert "processing_now=5" in result.output
    assert "available_slots=1" in result.output
