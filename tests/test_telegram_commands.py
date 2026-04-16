from __future__ import annotations

import uuid
from typing import Any
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import roughcut.telegram.commands as commands_mod
import roughcut.review.telegram_bot as telegram_bot_mod
from roughcut.telegram.commands import handle_telegram_command, handle_telegram_freeform_request, parse_telegram_command


async def _seed_job_for_telegram_rerun(
    job_id: uuid.UUID,
    *,
    quality_artifact: dict[str, Any] | None = None,
) -> None:
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import create_job_steps

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/telegram-rerun.mp4",
                source_name="telegram-rerun.mp4",
                status="done",
                language="zh-CN",
            )
        )
        for step in create_job_steps(job_id):
            step.status = "done"
            session.add(step)
        if quality_artifact is not None:
            session.add(
                Artifact(
                    job_id=job_id,
                    artifact_type="quality_assessment",
                    data_json=quality_artifact,
                )
            )
        await session.commit()


def test_parse_telegram_command_trims_bot_suffix():
    command = parse_telegram_command("/status@roughcut_bot")

    assert command is not None
    assert command.name == "status"
    assert command.args == []


@pytest.mark.asyncio
async def test_handle_status_command_reports_service_matrix(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(commands_mod, "_has_process", lambda needle: "roughcut.cli api" in needle)
    monkeypatch.setattr(
        commands_mod,
        "build_service_status",
        lambda api_running: {
            "services": {
                "api": api_running,
                "telegram_agent": True,
                "orchestrator": True,
                "media_worker": False,
                "llm_worker": True,
                "postgres": True,
                "redis": True,
            },
            "runtime": {
                "readiness_status": "ready",
                "orchestrator_lock": {"status": "held"},
            },
        },
    )
    async def fake_build_service_status(api_running: bool):
        return {
            "services": {
                "api": api_running,
                "telegram_agent": True,
                "orchestrator": True,
                "media_worker": False,
                "llm_worker": True,
                "postgres": True,
                "redis": True,
            },
            "runtime": {
                "readiness_status": "ready",
                "orchestrator_lock": {"status": "held"},
            },
        }
    monkeypatch.setattr(commands_mod, "build_service_status", fake_build_service_status)
    handled = await handle_telegram_command("/status", send_text=fake_send_text)

    assert handled is True
    assert sent
    assert "Telegram Agent" in sent[0]
    assert "Orchestrator" in sent[0]
    assert "Runtime Ready" in sent[0]
    assert "未运行" in sent[0]


@pytest.mark.asyncio
async def test_handle_jobs_command_formats_latest_jobs(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    class FakeResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return list(self._items)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, stmt):
            return FakeResult(
                [
                    SimpleNamespace(
                        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        source_name="a.mp4",
                        status="done",
                        steps=[SimpleNamespace(step_name="render", status="done", started_at=None, finished_at=1)],
                    )
                ]
            )

    monkeypatch.setattr(commands_mod, "get_session_factory", lambda: (lambda: FakeSession()))

    handled = await handle_telegram_command("/jobs 1", send_text=fake_send_text)

    assert handled is True
    assert sent
    assert "a.mp4" in sent[0]
    assert "render:done" in sent[0]


@pytest.mark.asyncio
async def test_handle_review_content_pass(monkeypatch):
    sent: list[str] = []
    confirmed: list[dict] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    async def fake_get_content_profile(job_id, session):
        return SimpleNamespace(review_step_status="pending")

    async def fake_confirm_content_profile(job_id, body, session):
        confirmed.append(body.model_dump(exclude_none=True))

    monkeypatch.setattr(commands_mod, "get_content_profile", fake_get_content_profile)
    monkeypatch.setattr(commands_mod, "confirm_content_profile", fake_confirm_content_profile)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(commands_mod, "get_session_factory", lambda: (lambda: FakeSession()))

    handled = await handle_telegram_command(
        "/review content 00000000-0000-0000-0000-000000000001 pass",
        send_text=fake_send_text,
    )

    assert handled is True
    assert confirmed == [{}]
    assert "已提交任务" in sent[0]


@pytest.mark.asyncio
async def test_apply_subtitle_review_returns_artifact_summary_when_no_pending_candidates(monkeypatch):
    async def fake_generate_report(job_id, session):
        return SimpleNamespace(items=[])

    async def fake_load_subtitle_review_artifacts(job_id, session):
        return {
            "subtitle_term_resolution_patch": {
                "metrics": {"patch_count": 2, "pending_count": 1, "accepted_count": 0, "auto_applied_count": 1},
            }
        }

    monkeypatch.setattr(commands_mod, "generate_report", fake_generate_report)
    monkeypatch.setattr(telegram_bot_mod, "_build_pending_subtitle_candidates", lambda report: [])
    monkeypatch.setattr(telegram_bot_mod, "_load_subtitle_review_artifacts", fake_load_subtitle_review_artifacts)
    monkeypatch.setattr(
        telegram_bot_mod,
        "_build_subtitle_review_artifact_lines",
        lambda artifacts: ["- 处理动作：先人工确认 1 条术语候选，再继续后续摘要与成片流程。"],
    )

    message = await commands_mod._apply_subtitle_review(
        session=SimpleNamespace(),
        job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        action="pass",
        note="",
    )

    assert "当前没有待审核字幕纠错候选" in message
    assert "最新字幕审校状态：" in message
    assert "先人工确认 1 条术语候选" in message


@pytest.mark.asyncio
async def test_handle_rerun_command_uses_quality_assessment_default_plan(db_engine):
    from roughcut.db.models import Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    job_id = uuid.uuid4()
    await _seed_job_for_telegram_rerun(
        job_id,
        quality_artifact={
            "score": 84.0,
            "grade": "B",
            "issue_codes": ["subtitle_sync_issue"],
            "recommended_rerun_step": "render",
            "recommended_rerun_steps": ["render", "final_review", "platform_package"],
        },
    )

    handled = await handle_telegram_command(f"/rerun {job_id}", send_text=fake_send_text)

    assert handled is True
    assert sent
    assert f"任务 {job_id}：" in sent[0]
    assert "已接受重跑请求，等待调度器从 render 接管。" in sent[0]
    assert "render -> final_review -> platform_package" in sent[0]

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()
        actions = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalars().all()

    assert job is not None
    assert job.status == "processing"
    step_map = {step.step_name: step for step in steps}
    assert step_map["render"].status == "pending"
    assert step_map["render"].metadata_["rerun_requested_via"] == "telegram"
    assert step_map["render"].metadata_["rerun_issue_codes"] == ["subtitle_sync_issue"]
    assert len(actions) == 1
    assert actions[0].target_type == "quality_rerun"


@pytest.mark.asyncio
async def test_handle_rerun_command_supports_explicit_step(db_engine):
    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory

    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    job_id = uuid.uuid4()
    await _seed_job_for_telegram_rerun(job_id)

    handled = await handle_telegram_command(
        f"/rerun {job_id} --step subtitle_term_resolution 术语链路重跑",
        send_text=fake_send_text,
    )

    assert handled is True
    assert sent
    assert "已接受重跑请求，等待调度器从 subtitle_term_resolution 接管。" in sent[0]
    assert "备注：术语链路重跑" in sent[0]

    async with get_session_factory()() as session:
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()

    step_map = {step.step_name: step for step in steps}
    assert step_map["subtitle_term_resolution"].status == "pending"
    assert step_map["subtitle_term_resolution"].metadata_["rerun_requested_via"] == "telegram"
    assert step_map["subtitle_term_resolution"].metadata_["rerun_start_step"] == "subtitle_term_resolution"
    assert step_map["subtitle_term_resolution"].metadata_["rerun_request_note"] == "术语链路重跑"


@pytest.mark.asyncio
async def test_handle_run_implement_requires_confirmation(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    setattr(fake_send_text, "_telegram_chat_id", "321")

    created = []

    def fake_create_task_record(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(task_id="task-1")

    monkeypatch.setattr(
        commands_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_claude_enabled=True, telegram_agent_acp_command=""),
    )
    monkeypatch.setattr(commands_mod, "create_task_record", fake_create_task_record)

    handled = await handle_telegram_command(
        '/run claude implement --task "修复 telegram agent"',
        send_text=fake_send_text,
    )

    assert handled is True
    assert created[0]["status"] == "awaiting_confirmation"
    assert "/confirm task-1" in sent[0]


@pytest.mark.asyncio
async def test_handle_run_build_submits_agent_task_without_confirmation(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    setattr(fake_send_text, "_telegram_chat_id", "321")

    created = []
    submitted = []

    def fake_create_task_record(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(task_id="task-build", **kwargs)

    monkeypatch.setattr(
        commands_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_claude_enabled=False, telegram_agent_acp_command="", telegram_agent_codex_command="codex"),
    )
    monkeypatch.setattr(commands_mod.shutil, "which", lambda name: "C:/tools/codex.exe" if name == "codex" else None)
    monkeypatch.setattr(commands_mod, "create_task_record", fake_create_task_record)
    monkeypatch.setattr(commands_mod, "submit_agent_task", lambda record: submitted.append(record) or record)

    handled = await handle_telegram_command(
        '/run codex build --task "执行 pnpm build 并汇总失败原因"',
        send_text=fake_send_text,
    )

    assert handled is True
    assert created[0]["preset"] == "build"
    assert created[0]["status"] == "queued"
    assert submitted
    assert "任务已提交" in sent[0]


@pytest.mark.asyncio
async def test_handle_unknown_command_creates_extension_task(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    setattr(fake_send_text, "_telegram_chat_id", "321")

    created = []

    def fake_create_task_record(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(task_id="task-unknown")

    monkeypatch.setattr(
        commands_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_agent_claude_enabled=False,
            telegram_agent_claude_command="claude",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
        ),
    )
    monkeypatch.setattr(commands_mod, "create_task_record", fake_create_task_record)

    handled = await handle_telegram_command("/refactor-telegram-agent", send_text=fake_send_text)

    assert handled is True
    assert created[0]["provider"] == "acp"
    assert created[0]["preset"] == "extend"
    assert created[0]["status"] == "awaiting_confirmation"
    assert "/confirm task-unknown" in sent[0]


@pytest.mark.asyncio
async def test_handle_freeform_request_queues_triage_task(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    setattr(fake_send_text, "_telegram_chat_id", "321")

    created = []
    submitted = []

    def fake_create_task_record(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(task_id="task-freeform", **kwargs)

    monkeypatch.setattr(
        commands_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_agent_claude_enabled=False,
            telegram_agent_claude_command="claude",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
        ),
    )
    monkeypatch.setattr(commands_mod, "create_task_record", fake_create_task_record)
    monkeypatch.setattr(commands_mod, "submit_agent_task", lambda record: submitted.append(record) or record)

    handled = await handle_telegram_freeform_request("请帮我分析 telegram agent 的链路问题", send_text=fake_send_text)

    assert handled is True
    assert created[0]["provider"] == "acp"
    assert created[0]["preset"] == "triage"
    assert created[0]["status"] == "queued"
    assert submitted
    assert "已将请求交给 Telegram agent" in sent[0]


@pytest.mark.asyncio
async def test_handle_freeform_build_request_queues_build_task(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    setattr(fake_send_text, "_telegram_chat_id", "321")

    created = []
    submitted = []

    def fake_create_task_record(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(task_id="task-build-freeform", **kwargs)

    monkeypatch.setattr(
        commands_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_enabled=True,
            telegram_agent_claude_enabled=False,
            telegram_agent_claude_command="claude",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
        ),
    )
    monkeypatch.setattr(commands_mod, "create_task_record", fake_create_task_record)
    monkeypatch.setattr(commands_mod, "submit_agent_task", lambda record: submitted.append(record) or record)

    handled = await handle_telegram_freeform_request("帮我把前端构建一下，顺便看看报错", send_text=fake_send_text)

    assert handled is True
    assert created[0]["provider"] == "acp"
    assert created[0]["preset"] == "build"
    assert created[0]["status"] == "queued"
    assert "构建/验证请求" in created[0]["task_text"]
    assert submitted
    assert "已将请求交给 Telegram agent" in sent[0]


def test_acp_available_prefers_settings_backend_over_env(monkeypatch):
    settings = SimpleNamespace(
        telegram_agent_acp_command="",
        acp_bridge_backend="codex",
        acp_bridge_fallback_backend="claude",
        telegram_agent_codex_command="codex",
        telegram_agent_claude_command="claude",
        telegram_agent_claude_enabled=False,
    )
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.setattr(
        commands_mod.shutil,
        "which",
        lambda name: "C:/tools/codex.exe" if name == "codex" else None,
    )

    assert commands_mod._acp_available(settings) is True
    assert commands_mod._select_agent_provider(settings) == "acp"


def test_acp_available_uses_fallback_backend_when_primary_missing(monkeypatch):
    settings = SimpleNamespace(
        telegram_agent_acp_command="",
        acp_bridge_backend="codex",
        acp_bridge_fallback_backend="claude",
        telegram_agent_codex_command="codex",
        telegram_agent_claude_command="claude",
        telegram_agent_claude_enabled=True,
    )
    monkeypatch.setattr(
        commands_mod.shutil,
        "which",
        lambda name: "C:/tools/claude.exe" if name == "claude" else None,
    )

    assert commands_mod._acp_available(settings) is True


@pytest.mark.asyncio
async def test_handle_confirm_command_submits_task(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(
        commands_mod,
        "confirm_agent_task",
        lambda task_id: SimpleNamespace(task_id=task_id, status="queued"),
    )

    handled = await handle_telegram_command("/confirm abc-123", send_text=fake_send_text)

    assert handled is True
    assert "已确认并提交任务" in sent[0]


@pytest.mark.asyncio
async def test_handle_cancel_command_marks_task_cancelled(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(
        commands_mod,
        "cancel_agent_task",
        lambda task_id: SimpleNamespace(task_id=task_id, status="cancelled"),
    )

    handled = await handle_telegram_command("/cancel abc-123", send_text=fake_send_text)

    assert handled is True
    assert "已取消任务" in sent[0]


@pytest.mark.asyncio
async def test_handle_presets_command_lists_known_presets(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    handled = await handle_telegram_command("/presets", send_text=fake_send_text)

    assert handled is True
    assert "claude/inspect" in sent[0]
    assert "acp/delegate" in sent[0]


@pytest.mark.asyncio
async def test_handle_task_command_full_includes_persisted_payload(monkeypatch):
    sent: list[str] = []

    async def fake_send_text(text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(
        commands_mod,
        "get_agent_task_status",
        lambda task_id: {
            "task_id": task_id,
            "status": "success",
            "provider": "claude",
            "preset": "inspect",
            "result_excerpt": "ok",
            "result_path": "E:/tmp/task.json",
            "error_text": "",
        },
    )
    monkeypatch.setattr(
        commands_mod,
        "load_agent_task_result",
        lambda task_id: {"stdout": "full output"},
    )

    handled = await handle_telegram_command("/task abc-123 --full", send_text=fake_send_text)

    assert handled is True
    assert "结果文件" in sent[0]
    assert "完整结果" in sent[0]
