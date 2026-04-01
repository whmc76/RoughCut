from __future__ import annotations

import json
import os
import shlex
import shutil
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
_AGENT_REQUEST_KEYWORDS = (
    "agent",
    "telegram",
    "command",
    "commands",
    "acp",
    "claude",
    "codex",
    "bug",
    "error",
    "fix",
    "review",
    "plan",
    "implement",
    "optimize",
    "refactor",
    "unsupported",
    "未知命令",
    "不支持",
    "指令",
    "命令",
    "修复",
    "错误",
    "排查",
    "分析",
    "优化",
    "重构",
    "扩展",
    "支持",
    "实现",
    "链路",
    "结构",
)
_EDIT_REQUEST_KEYWORDS = (
    "fix",
    "implement",
    "optimize",
    "refactor",
    "support",
    "extend",
    "repair",
    "新增",
    "扩展",
    "支持",
    "实现",
    "修复",
    "优化",
    "重构",
    "改造",
    "补齐",
)


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

    if await _dispatch_agent_request(
        text=command.raw_text,
        send_text=send_text,
        source="unknown_command",
    ):
        return True

    await send_text(
        "未知命令。可用命令：/status、/jobs [limit]、/job <job_id>、"
        "/run <claude|codex|acp> <preset> --task \"...\" [--path ...] [--job ...]、"
        "/task <task_id> [--full]、/tasks [limit]、/presets、/confirm <task_id>、/cancel <task_id>、"
        "/review [content|subtitle] <job_id> <pass|reject|note> [备注]"
    )
    return True


async def handle_telegram_freeform_request(text: str, *, send_text: SendText) -> bool:
    return await _dispatch_agent_request(
        text=text,
        send_text=send_text,
        source="freeform",
    )


async def _handle_status_command(send_text: SendText) -> None:
    api_running = _has_process("roughcut.cli api") or _has_process("uvicorn roughcut.main:app")
    payload = await build_service_status(api_running=api_running)
    services = payload["services"]
    runtime = payload.get("runtime") or {}
    orchestrator_lock = runtime.get("orchestrator_lock") or {}
    lines = [
        "服务状态：",
        f"- API：{_render_service_state(services['api'])}",
        f"- Telegram Agent：{_render_service_state(services['telegram_agent'])}",
        f"- Orchestrator：{_render_service_state(services['orchestrator'])}",
        f"- Media Worker：{_render_service_state(services['media_worker'])}",
        f"- LLM Worker：{_render_service_state(services['llm_worker'])}",
        f"- PostgreSQL：{_render_service_state(services['postgres'])}",
        f"- Redis：{_render_service_state(services['redis'])}",
        f"- Runtime Ready：{runtime.get('readiness_status', 'unknown')}",
        f"- Orchestrator Lock：{orchestrator_lock.get('status', 'unknown')}",
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
    if provider == "claude" and not _claude_command_available(settings):
        await send_text(
            "Claude CLI 执行器不可用。请确认 `TELEGRAM_AGENT_CLAUDE_ENABLED=true`，"
            "并且 `TELEGRAM_AGENT_CLAUDE_COMMAND` 可执行。"
        )
        return
    if provider == "codex" and not _codex_command_available(settings):
        await send_text(
            "Codex CLI 执行器不可用。请确认本机已安装 `codex`，"
            "或设置 `TELEGRAM_AGENT_CODEX_COMMAND` 指向可执行命令。"
        )
        return
    if provider == "acp" and not _acp_available(settings):
        await send_text(
            "ACP 执行器不可用。请配置 `TELEGRAM_AGENT_ACP_COMMAND`，"
            "或确保内置 ACP bridge 所需的 Claude/Codex 命令可执行。"
        )
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
            "用法：/run <claude|codex|acp> <preset> --task \"...\" [--path relative/path] [--job <job_id>]\n"
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


async def _dispatch_agent_request(text: str, *, send_text: SendText, source: str) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "telegram_agent_enabled", False)):
        return False

    normalized = str(text or "").strip()
    if not normalized:
        return False
    if source == "freeform" and not _looks_like_agent_request(normalized):
        return False

    provider = _select_agent_provider(settings)
    if not provider:
        return False
    preset_name = _select_agent_preset(provider, normalized, source=source)
    preset = get_preset(provider, preset_name)
    if preset is None:
        return False

    task_text = _build_agent_request_task_text(normalized, source=source)
    record = create_task_record(
        chat_id=_chat_id_from_sender(send_text),
        provider=provider,
        preset=preset_name,
        task_text=task_text,
        status="awaiting_confirmation" if preset.requires_confirmation else "queued",
        confirmation_required=preset.requires_confirmation,
    )
    if preset.requires_confirmation:
        await send_text(
            f"已识别为 Telegram agent 扩展请求，等待确认：{record.task_id}\n"
            f"- preset：{provider}/{preset_name}\n"
            f"- 原始请求：{_truncate_request_text(normalized)}\n"
            "该任务可能会修改代码、补充命令或优化链路。"
            f"\n回复：/confirm {record.task_id}"
        )
        return True

    submit_agent_task(record)
    await send_text(
        f"已将请求交给 Telegram agent：{record.task_id}\n"
        f"- preset：{provider}/{preset_name}\n"
        f"- 原始请求：{_truncate_request_text(normalized)}"
    )
    return True


def _build_agent_request_task_text(text: str, *, source: str) -> str:
    if source == "unknown_command":
        return (
            f"Telegram 收到未支持命令：{text}\n"
            "请先判断是否已有等价命令或现成功能；如果没有，请补齐最小可行实现，"
            "让后续相似请求可以被 Telegram agent 直接识别、分发或执行。"
        )
    return (
        f"这是来自 Telegram agent 的自然语言工程请求：{text}\n"
        "请优先处理复杂错误、结构优化和链路优化；如果需要新增 Telegram 命令、"
        "增强未知指令兜底或扩展 ACP/Claude Code/Codex 接入，也请一并处理。"
    )


def _looks_like_agent_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in _AGENT_REQUEST_KEYWORDS)


def _select_agent_provider(settings) -> str | None:
    if _acp_available(settings):
        return "acp"
    if _codex_command_available(settings):
        return "codex"
    if _claude_command_available(settings):
        return "claude"
    return None


def _select_agent_preset(provider: str, text: str, *, source: str) -> str:
    if source == "unknown_command" or _looks_like_edit_request(text):
        return "extend" if provider == "acp" else "implement"
    return "triage" if provider == "acp" else "plan"


def _looks_like_edit_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in _EDIT_REQUEST_KEYWORDS)


def _truncate_request_text(text: str, *, max_chars: int = 180) -> str:
    normalized = str(text or "").strip().replace("\r", " ").replace("\n", " ")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 16)].rstrip() + " ...[truncated]"


def _claude_command_name(settings) -> str:
    return str(getattr(settings, "telegram_agent_claude_command", "claude") or "claude").strip()


def _codex_command_name(settings) -> str:
    return str(
        getattr(settings, "telegram_agent_codex_command", "")
        or os.getenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
        or "codex"
    ).strip()


def _configured_acp_backend(settings) -> str:
    return str(
        getattr(settings, "acp_bridge_backend", "")
        or os.getenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "codex")
        or "codex"
    ).strip().lower()


def _configured_acp_fallback_backend(settings) -> str:
    return str(
        getattr(settings, "acp_bridge_fallback_backend", "")
        or os.getenv("ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND", "claude")
        or "claude"
    ).strip().lower()


def _configured_acp_backends(settings) -> list[str]:
    backends: list[str] = []
    claude_enabled = bool(getattr(settings, "telegram_agent_claude_enabled", False))
    for item in (_configured_acp_backend(settings), _configured_acp_fallback_backend(settings)):
        normalized = str(item or "").strip().lower()
        if normalized not in {"claude", "codex"}:
            continue
        if normalized == "claude" and not claude_enabled:
            continue
        if normalized not in backends:
            backends.append(normalized)
    return backends


def _claude_command_available(settings) -> bool:
    if not bool(getattr(settings, "telegram_agent_claude_enabled", False)):
        return False
    return bool(shutil.which(_claude_command_name(settings)))


def _codex_command_available(settings) -> bool:
    return bool(shutil.which(_codex_command_name(settings)))


def _acp_available(settings) -> bool:
    explicit_command = str(getattr(settings, "telegram_agent_acp_command", "") or "").strip()
    if explicit_command:
        return True
    for backend in _configured_acp_backends(settings):
        if backend == "codex" and _codex_command_available(settings):
            return True
        if backend == "claude" and _claude_command_available(settings):
            return True
    return False
