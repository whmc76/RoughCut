from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import roughcut.cli as cli_mod
from roughcut.cli import QualityAuditRow


def test_init_creates_project_dirs_and_env(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    (tmp_path / ".env.example").write_text("OUTPUT_DIR=output\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir="output", render_debug_dir="output/test/render-debug"),
    )

    result = runner.invoke(cli_mod.cli, ["init"])

    assert result.exit_code == 0
    assert (tmp_path / "output").exists()
    assert (tmp_path / "output" / "test" / "render-debug").exists()
    assert (tmp_path / "watch").exists()
    assert (tmp_path / ".env").exists()


def test_doctor_reports_missing_ffmpeg_as_failure(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir="output", render_debug_dir="output/test/render-debug"),
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
