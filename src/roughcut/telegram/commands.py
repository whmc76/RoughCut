from __future__ import annotations

import json
import shlex
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from roughcut.api.control import _has_process, build_service_status
from roughcut.api.jobs import apply_review, confirm_content_profile, get_content_profile
from roughcut.api.schemas import ContentProfileConfirmIn, ReviewActionCreate, ReviewApplyRequest
from roughcut.config import get_settings
from roughcut.db.models import Job
from roughcut.db.session import get_session_factory
from roughcut.review.report import generate_report
from roughcut.telegram.presets import get_preset
from roughcut.telegram.task_service import (
    cancel_agent_task,
    confirm_agent_task,
    create_task_record,
    get_agent_task_status,
    list_agent_task_records,
    load_agent_task_result,
    preset_help_lines,
    submit_agent_task,
)

SendText = Callable[[str], Awaitable[None]]
_DEFAULT_JOB_LIMIT = 5
_MAX_JOB_LIMIT = 10


@dataclass
class TelegramCommand:
    name: str
    args: list[str]
    raw_text: str


def parse_telegram_command(text: str) -> TelegramCommand | None:
    normalized = str(text or "").strip()
    if not normalized.startswith("/"):
        return None
    try:
        parts = shlex.split(normalized)
    except ValueError:
        parts = normalized.split()
    if not parts:
        return None
    name = parts[0].lstrip("/").split("@", 1)[0].strip().lower()
    return TelegramCommand(name=name, args=parts[1:], raw_text=normalized)


async def handle_telegram_command(text: str, *, send_text: SendText) -> bool:
    command = parse_telegram_command(text)
    if command is None:
        return False

    if command.name == "status":
        await _handle_status_command(send_text)
        return True
    if command.name == "jobs":
        await _handle_jobs_command(command.args, send_text)
        return True
    if command.name == "job":
        await _handle_job_command(command.args, send_text)
        return True
    if command.name == "run":
        await _handle_run_command(command.args, send_text)
        return True
    if command.name == "task":
        await _handle_task_command(command.args, send_text)
        return True
    if command.name == "tasks":
        await _handle_tasks_command(command.args, send_text)
        return True
    if command.name == "confirm":
        await _handle_confirm_command(command.args, send_text)
        return True
    if command.name == "cancel":
        await _handle_cancel_command(command.args, send_text)
        return True
    if command.name == "presets":
        await _handle_presets_command(send_text)
        return True
    if command.name == "review":
        await _handle_review_command(command.args, send_text)
        return True
    if command.name in {"start", "help", "whoami", "id"}:
        return False

    await send_text(
        "未知命令。可用命令：/status、/jobs [limit]、/job <job_id>、"
        "/run <claude|acp> <preset> --task \"...\" [--path ...] [--job ...]、"
        "/task <task_id> [--full]、/tasks [limit]、/presets、/confirm <task_id>、/cancel <task_id>、"
        "/review [content|subtitle] <job_id> <pass|reject|note> [备注]"
    )
    return True


async def _handle_status_command(send_text: SendText) -> None:
    api_running = _has_process("roughcut.cli api") or _has_process("uvicorn roughcut.main:app")
    payload = build_service_status(api_running=api_running)
    services = payload["services"]
    lines = [
        "服务状态：",
        f"- API：{_render_service_state(services['api'])}",
        f"- Telegram Agent：{_render_service_state(services['telegram_agent'])}",
        f"- Orchestrator：{_render_service_state(services['orchestrator'])}",
        f"- Media Worker：{_render_service_state(services['media_worker'])}",
        f"- LLM Worker：{_render_service_state(services['llm_worker'])}",
        f"- PostgreSQL：{_render_service_state(services['postgres'])}",
        f"- Redis：{_render_service_state(services['redis'])}",
        f"- MinIO：{_render_service_state(services['minio'])}",
    ]
    await send_text("\n".join(lines))


async def _handle_jobs_command(args: list[str], send_text: SendText) -> None:
    limit = _DEFAULT_JOB_LIMIT
    if args:
        try:
            limit = max(1, min(_MAX_JOB_LIMIT, int(args[0])))
        except ValueError:
            await send_text("用法：/jobs [limit]，limit 取 1 到 10。")
            return

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job)
            .options(selectinload(Job.steps))
            .order_by(Job.updated_at.desc(), Job.created_at.desc())
            .limit(limit)
        )
        jobs = result.scalars().all()

    if not jobs:
        await send_text("当前没有任务。")
        return

    lines = ["最近任务："]
    for index, job in enumerate(jobs, start=1):
        lines.append(f"{index}. {job.source_name}")
        lines.append(f"   {job.id} | 状态：{job.status} | 最近步骤：{_summarize_latest_step(job)}")
    await send_text("\n".join(lines))


async def _handle_job_command(args: list[str], send_text: SendText) -> None:
    if not args:
        await send_text("用法：/job <job_id>")
        return
    try:
        job_id = uuid.UUID(str(args[0]).strip())
    except ValueError:
        await send_text("job_id 格式无效。")
        return

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job)
            .options(selectinload(Job.steps))
            .where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()

    if job is None:
        await send_text(f"任务不存在：{job_id}")
        return

    lines = [
        f"任务：{job.source_name}",
        f"- Job ID：{job.id}",
        f"- 状态：{job.status}",
        f"- 工作流：{job.workflow_mode}",
        f"- 增强模式：{', '.join(job.enhancement_modes or []) if job.enhancement_modes else '未启用'}",
        f"- 最近步骤：{_summarize_latest_step(job)}",
    ]
    await send_text("\n".join(lines))


async def _handle_run_command(args: list[str], send_text: SendText) -> None:
    parsed = _parse_run_args(args)
    if isinstance(parsed, str):
        await send_text(parsed)
        return

    provider = parsed["provider"]
    preset_name = parsed["preset"]
    preset = get_preset(provider, preset_name)
    if preset is None:
        await send_text(f"未知 preset：{provider}/{preset_name}")
        return
    settings = get_settings()
    if provider == "claude" and not bool(getattr(settings, "telegram_agent_claude_enabled", False)):
        await send_text("Claude CLI 执行器未启用，请先配置 `TELEGRAM_AGENT_CLAUDE_ENABLED=true`。")
        return
    if preset.requires_task and not parsed["task"]:
        await send_text("该 preset 需要 `--task`。")
        return

    record = create_task_record(
        chat_id=_chat_id_from_sender(send_text),
        provider=provider,
        preset=preset_name,
        task_text=parsed["task"],
        scope_path=parsed["path"],
        job_id=parsed["job"],
        status="awaiting_confirmation" if preset.requires_confirmation else "queued",
        confirmation_required=preset.requires_confirmation,
    )
    if preset.requires_confirmation:
        await send_text(
            f"任务已创建，等待确认：{record.task_id}\n"
            f"- preset：{provider}/{preset_name}\n"
            f"- 范围：{parsed['path'] or '/'}\n"
            f"- 任务：{parsed['task']}\n"
            "执行该 preset 可能改动代码，请回复：/confirm "
            f"{record.task_id}"
        )
        return

    submit_agent_task(record)
    await send_text(
        f"任务已提交：{record.task_id}\n"
        f"- preset：{provider}/{preset_name}\n"
        f"- 范围：{parsed['path'] or '/'}\n"
        f"- 任务：{parsed['task'] or '未提供'}"
    )


async def _handle_task_command(args: list[str], send_text: SendText) -> None:
    if not args:
        await send_text("用法：/task <task_id>")
        return
    task_id = str(args[0]).strip()
    show_full = any(str(item).strip().lower() in {"--full", "full"} for item in args[1:])
    payload = get_agent_task_status(task_id)
    lines = [
        f"任务：{payload.get('task_id', task_id)}",
        f"- 状态：{payload.get('status', 'unknown')}",
        f"- Provider：{payload.get('provider', '') or 'unknown'}",
        f"- Preset：{payload.get('preset', '') or 'unknown'}",
    ]
    result_path = str(payload.get("result_path") or "").strip()
    if result_path:
        lines.append(f"- 结果文件：{result_path}")
    result_excerpt = str(payload.get("result_excerpt") or "").strip()
    error_text = str(payload.get("error_text") or "").strip()
    if result_excerpt:
        lines.append("结果摘要：")
        lines.append(result_excerpt)
    if error_text:
        lines.append("错误：")
        lines.append(error_text)
    if show_full:
        full_payload = load_agent_task_result(task_id)
        if full_payload:
            lines.append("完整结果：")
            lines.append(json.dumps(full_payload, ensure_ascii=False, indent=2)[:6000])
    await send_text("\n".join(lines))


async def _handle_tasks_command(args: list[str], send_text: SendText) -> None:
    limit = _DEFAULT_JOB_LIMIT
    if args:
        try:
            limit = max(1, min(_MAX_JOB_LIMIT, int(args[0])))
        except ValueError:
            await send_text("用法：/tasks [limit]，limit 取 1 到 10。")
            return

    records = list_agent_task_records(chat_id=_chat_id_from_sender(send_text), limit=limit)
    if not records:
        await send_text("当前没有已记录的 Telegram agent 任务。")
        return
    lines = ["最近 agent 任务："]
    for item in records:
        payload = get_agent_task_status(item.task_id)
        lines.append(
            f"- {item.task_id} | {item.provider}/{item.preset} | {payload.get('status', item.status)}"
        )
        if item.scope_path:
            lines.append(f"  scope={item.scope_path}")
    await send_text("\n".join(lines))


async def _handle_confirm_command(args: list[str], send_text: SendText) -> None:
    if not args:
        await send_text("用法：/confirm <task_id>")
        return
    record = confirm_agent_task(args[0])
    if record is None:
        await send_text(f"任务不存在：{args[0]}")
        return
    if record.status != "queued":
        await send_text(f"任务 {record.task_id} 当前状态为 {record.status}，无需确认。")
        return
    await send_text(f"已确认并提交任务：{record.task_id}")


async def _handle_cancel_command(args: list[str], send_text: SendText) -> None:
    if not args:
        await send_text("用法：/cancel <task_id>")
        return
    record = cancel_agent_task(args[0])
    if record is None:
        await send_text(f"任务不存在：{args[0]}")
        return
    if record.status != "cancelled":
        await send_text(f"任务 {record.task_id} 当前状态为 {record.status}，无法取消。")
        return
    await send_text(f"已取消任务：{record.task_id}")


async def _handle_presets_command(send_text: SendText) -> None:
    await send_text("可用 preset：\n" + "\n".join(preset_help_lines()))


async def _handle_review_command(args: list[str], send_text: SendText) -> None:
    if len(args) < 2:
        await send_text(
            "用法：/review [content|subtitle] <job_id> <pass|reject|note> [备注]"
        )
        return

    review_kind: str | None = None
    offset = 0
    if args[0].lower() in {"content", "subtitle"}:
        review_kind = args[0].lower()
        offset = 1

    if len(args) < offset + 2:
        await send_text(
            "用法：/review [content|subtitle] <job_id> <pass|reject|note> [备注]"
        )
        return

    try:
        job_id = uuid.UUID(str(args[offset]).strip())
    except ValueError:
        await send_text("job_id 格式无效。")
        return

    action = str(args[offset + 1]).strip().lower()
    note = " ".join(args[offset + 2 :]).strip()

    factory = get_session_factory()
    async with factory() as session:
        try:
            if review_kind is None:
                review_kind = await _infer_review_kind(session, job_id)
            if review_kind == "content":
                message = await _apply_content_review(session, job_id, action, note)
            elif review_kind == "subtitle":
                message = await _apply_subtitle_review(session, job_id, action, note)
            else:
                message = "当前没有可处理的内容审核或字幕审核。"
        except HTTPException as exc:
            message = str(exc.detail)
        except Exception as exc:
            message = f"审核命令执行失败：{exc}"

    await send_text(message)


def _parse_run_args(args: list[str]) -> dict[str, str] | str:
    if len(args) < 2:
        return (
            "用法：/run <claude|acp> <preset> --task \"...\" [--path relative/path] [--job <job_id>]\n"
            + "\n".join(["可用 preset：", *preset_help_lines()])
        )
    provider = str(args[0]).strip().lower()
    preset = str(args[1]).strip().lower()
    values = {"provider": provider, "preset": preset, "task": "", "path": "", "job": ""}
    index = 2
    while index < len(args):
        token = str(args[index]).strip()
        if token in {"--task", "--path", "--job"}:
            if index + 1 >= len(args):
                return f"缺少参数值：{token}"
            value = str(args[index + 1]).strip()
            if token == "--task":
                values["task"] = value
            elif token == "--path":
                values["path"] = value
            elif token == "--job":
                values["job"] = value
            index += 2
            continue
        if not values["task"]:
            values["task"] = " ".join(args[index:]).strip()
            break
        return f"无法解析参数：{token}"
    return values


async def _infer_review_kind(session, job_id: uuid.UUID) -> str | None:
    review = await get_content_profile(job_id, session)
    if str(review.review_step_status or "").strip() != "done":
        return "content"

    report = await generate_report(job_id, session)
    from roughcut.review.telegram_bot import _build_pending_subtitle_candidates

    if _build_pending_subtitle_candidates(report):
        return "subtitle"
    return None


async def _apply_content_review(session, job_id: uuid.UUID, action: str, note: str) -> str:
    review = await get_content_profile(job_id, session)
    if str(review.review_step_status or "").strip() == "done":
        return f"任务 {job_id} 的内容核对已经处理完成。"

    normalized_action = _normalize_review_action(action)
    if normalized_action == "pass":
        payload: dict = {}
    else:
        note_text = note.strip()
        if not note_text:
            return "内容审核的 reject / note 需要附带备注。"
        from roughcut.review.telegram_bot import _interpret_content_profile_reply

        if normalized_action == "reject":
            note_text = f"需要重写并重新核对：{note_text}"
        payload = await _interpret_content_profile_reply(review, note_text)

    await confirm_content_profile(job_id, ContentProfileConfirmIn(**payload), session)
    return f"已提交任务 {job_id} 的内容审核意见。"


async def _apply_subtitle_review(session, job_id: uuid.UUID, action: str, note: str) -> str:
    report = await generate_report(job_id, session)
    from roughcut.review.telegram_bot import (
        _build_pending_subtitle_candidates,
        _interpret_subtitle_review_reply,
    )

    candidates = _build_pending_subtitle_candidates(report)
    if not candidates:
        return f"任务 {job_id} 当前没有待审核字幕纠错候选。"

    normalized_action = _normalize_review_action(action)
    if normalized_action == "pass":
        actions = [
            {"correction_id": item.correction_id, "action": "accepted"}
            for item in candidates
        ]
    elif normalized_action == "reject":
        actions = [
            {"correction_id": item.correction_id, "action": "rejected"}
            for item in candidates
        ]
    else:
        note_text = note.strip()
        if not note_text:
            return "字幕审核的 note 需要附带备注。"
        actions = await _interpret_subtitle_review_reply(note_text, candidates)
        if not actions:
            return "没有从备注中解析出可执行的字幕审核动作。"

    request = ReviewApplyRequest(
        actions=[
            ReviewActionCreate(
                target_type="subtitle_correction",
                target_id=uuid.UUID(item["correction_id"]),
                action=item["action"],
                override_text=item.get("override_text"),
            )
            for item in actions
        ]
    )
    result = await apply_review(job_id, request, session)
    return f"已应用任务 {job_id} 的 {int(result.get('applied') or 0)} 条字幕审核意见。"


def _normalize_review_action(action: str) -> str:
    normalized = str(action or "").strip().lower()
    if normalized in {"pass", "approve", "approved", "accept", "accepted"}:
        return "pass"
    if normalized in {"reject", "rejected"}:
        return "reject"
    if normalized in {"note", "comment", "edit"}:
        return "note"
    return normalized


def _render_service_state(value: bool) -> str:
    return "运行中" if value else "未运行"


def _chat_id_from_sender(send_text: SendText) -> str:
    return str(getattr(send_text, "_telegram_chat_id", "") or "").strip()


def _summarize_latest_step(job: Job) -> str:
    steps = list(job.steps or [])
    if not steps:
        return "无"
    ranked = sorted(
        steps,
        key=lambda item: (
            bool(item.finished_at or item.started_at),
            item.finished_at or item.started_at,
            item.step_name,
        ),
        reverse=True,
    )
    latest = ranked[0]
    return f"{latest.step_name}:{latest.status}"
