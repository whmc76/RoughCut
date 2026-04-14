from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from roughcut.config import (
    get_settings,
    infer_coding_backends,
    normalize_coding_backend_name,
    resolve_coding_backend_model,
)
from roughcut.telegram.output_codec import decode_process_output
from roughcut.telegram.presets import get_preset
from roughcut.telegram.task_store import TelegramAgentTaskStore


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def execute_agent_preset(
    *,
    task_id: str = "",
    chat_id: str = "",
    provider: str,
    preset: str,
    task_text: str,
    scope_path: str = "",
    job_id: str = "",
) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "claude":
        return _execute_claude_preset(
            task_id=task_id,
            chat_id=chat_id,
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    if normalized_provider == "codex":
        return _execute_codex_preset(
            task_id=task_id,
            chat_id=chat_id,
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    if normalized_provider == "acp":
        return _execute_acp_preset(
            task_id=task_id,
            chat_id=chat_id,
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def _execute_claude_preset(
    *,
    task_id: str,
    chat_id: str,
    preset: str,
    task_text: str,
    scope_path: str,
    job_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    preset_config = get_preset("claude", preset)
    if preset_config is None:
        raise ValueError(f"Unknown Claude preset: {preset}")
    if not bool(getattr(settings, "telegram_agent_claude_enabled", False)):
        raise RuntimeError("telegram_agent_claude_enabled is false")

    command_name = str(getattr(settings, "telegram_agent_claude_command", "claude") or "claude").strip()
    resolved_command = shutil.which(command_name)
    if not resolved_command:
        raise RuntimeError(f"Claude command not found in PATH: {command_name}")
    model_name = resolve_coding_backend_model(
        "claude",
        settings=settings,
        explicit_model=(
            getattr(settings, "telegram_agent_claude_model", "")
            or os.getenv("TELEGRAM_AGENT_CLAUDE_MODEL", "")
        ),
    )

    repo_root = _repo_root()
    scope_value = _normalize_scope(scope_path, repo_root)
    prompt = _render_prompt(
        task_id=task_id,
        chat_id=chat_id,
        provider="claude",
        preset=preset,
        task_text=task_text,
        scope_path=scope_value,
        job_id=job_id,
    )
    permission_mode = "acceptEdits" if preset_config.allow_edits else "plan"
    command = [
        resolved_command,
        "-p",
        "--permission-mode",
        permission_mode,
        "--output-format",
        "text",
        "--add-dir",
        str(repo_root),
    ]
    if model_name:
        command.extend(["--model", model_name])
    timeout = max(30, int(getattr(settings, "telegram_agent_task_timeout_sec", 900)))
    result = subprocess.run(
        command,
        input=prompt.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=str(repo_root),
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = decode_process_output(result.stdout)
    stderr = decode_process_output(result.stderr)
    excerpt = _truncate_text(stdout or stderr, max_chars=int(getattr(settings, "telegram_agent_result_max_chars", 3500)))
    if result.returncode != 0:
        raise RuntimeError(stderr or stdout or f"claude exited with code {result.returncode}")
    return {
        "provider": "claude",
        "preset": preset,
        "cwd": str(repo_root),
        "scope_path": scope_value,
        "job_id": job_id,
        "stdout": stdout,
        "stderr": stderr,
        "excerpt": excerpt,
        "returncode": result.returncode,
    }


def _execute_codex_preset(
    *,
    task_id: str,
    chat_id: str,
    preset: str,
    task_text: str,
    scope_path: str,
    job_id: str,
) -> dict[str, Any]:
    preset_config = get_preset("codex", preset)
    if preset_config is None:
        raise ValueError(f"Unknown Codex preset: {preset}")

    settings = get_settings()
    command_name = str(
        getattr(settings, "telegram_agent_codex_command", "")
        or os.getenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
        or "codex"
    ).strip()
    resolved_command = shutil.which(command_name)
    if not resolved_command:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")
    model_name = resolve_coding_backend_model(
        "codex",
        settings=settings,
        explicit_model=(
            getattr(settings, "telegram_agent_codex_model", "")
            or os.getenv("TELEGRAM_AGENT_CODEX_MODEL", "")
        ),
    )

    repo_root = _repo_root()
    scope_value = _normalize_scope(scope_path, repo_root)
    prompt = _render_prompt(
        task_id=task_id,
        chat_id=chat_id,
        provider="codex",
        preset=preset,
        task_text=task_text,
        scope_path=scope_value,
        job_id=job_id,
    )
    sandbox_mode = "danger-full-access" if preset_config.allow_edits else "read-only"
    timeout = max(30, int(getattr(settings, "telegram_agent_task_timeout_sec", 900)))
    with tempfile.TemporaryDirectory(prefix="roughcut-codex-") as temp_dir:
        output_file = Path(temp_dir) / "last-message.txt"
        command = [
            resolved_command,
            "-a",
            "never",
        ]
        if model_name:
            command.extend(["-m", model_name])
        command.extend([
            "exec",
            "--color",
            "never",
            "-C",
            str(repo_root),
            "-s",
            sandbox_mode,
            "-o",
            str(output_file),
            prompt,
        ])
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            cwd=str(repo_root),
            env=os.environ.copy(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = ""
        if output_file.exists():
            stdout = decode_process_output(output_file.read_bytes())
        if not stdout:
            stdout = decode_process_output(result.stdout)
    stderr = decode_process_output(result.stderr)
    excerpt = _truncate_text(stdout or stderr, max_chars=int(getattr(settings, "telegram_agent_result_max_chars", 3500)))
    if result.returncode != 0:
        raise RuntimeError(stderr or stdout or f"codex exited with code {result.returncode}")
    return {
        "provider": "codex",
        "preset": preset,
        "cwd": str(repo_root),
        "scope_path": scope_value,
        "job_id": job_id,
        "stdout": stdout,
        "stderr": stderr,
        "excerpt": excerpt,
        "returncode": result.returncode,
    }


def _execute_acp_preset(
    *,
    task_id: str,
    chat_id: str,
    preset: str,
    task_text: str,
    scope_path: str,
    job_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    preset_config = get_preset("acp", preset)
    if preset_config is None:
        raise ValueError(f"Unknown ACP preset: {preset}")
    repo_root = _repo_root()
    bridge_command = str(getattr(settings, "telegram_agent_acp_command", "") or "").strip()
    if not bridge_command:
        bridge_command = _default_acp_bridge_command(repo_root)
    scope_value = _normalize_scope(scope_path, repo_root)
    payload = {
        "task_id": task_id,
        "chat_id": chat_id,
        "provider": "acp",
        "preset": preset,
        "task": task_text,
        "scope_path": scope_value,
        "job_id": job_id,
        "repo_root": str(repo_root),
        "prompt": _render_prompt(
            task_id=task_id,
            chat_id=chat_id,
            provider="acp",
            preset=preset,
            task_text=task_text,
            scope_path=scope_value,
            job_id=job_id,
        ),
    }
    env = os.environ.copy()
    env["ROUGHCUT_AGENT_PROVIDER"] = "acp"
    env["ROUGHCUT_AGENT_PRESET"] = preset
    env["ROUGHCUT_AGENT_SCOPE_PATH"] = scope_value
    env["ROUGHCUT_AGENT_JOB_ID"] = job_id
    env["ROUGHCUT_AGENT_TASK_ID"] = task_id
    env["ROUGHCUT_AGENT_CHAT_ID"] = chat_id
    backends = _configured_acp_backends(settings)
    if not backends:
        raise RuntimeError("ACP bridge has no enabled backend")
    bridge_backend = backends[0]
    bridge_fallback_backend = backends[1] if len(backends) > 1 else ""
    claude_command = str(getattr(settings, "telegram_agent_claude_command", "claude") or "claude").strip()
    claude_model = resolve_coding_backend_model(
        "claude",
        settings=settings,
        explicit_model=(
            getattr(settings, "acp_bridge_claude_model", "")
            or getattr(settings, "telegram_agent_claude_model", "")
            or os.getenv("TELEGRAM_AGENT_CLAUDE_MODEL", "")
            or os.getenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL", "")
        ),
    )
    codex_command = str(
        getattr(settings, "acp_bridge_codex_command", "")
        or getattr(settings, "telegram_agent_codex_command", "")
        or os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND", "")
        or os.getenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
        or "codex"
    ).strip()
    codex_model = resolve_coding_backend_model(
        "codex",
        settings=settings,
        explicit_model=(
            getattr(settings, "acp_bridge_codex_model", "")
            or getattr(settings, "telegram_agent_codex_model", "")
            or os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_MODEL", "")
            or os.getenv("TELEGRAM_AGENT_CODEX_MODEL", "")
        ),
    )
    env["ROUGHCUT_ACP_BRIDGE_BACKEND"] = bridge_backend
    if bridge_fallback_backend:
        env["ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND"] = bridge_fallback_backend
    if bool(getattr(settings, "telegram_agent_claude_enabled", False)) and claude_command:
        env["TELEGRAM_AGENT_CLAUDE_COMMAND"] = claude_command
        env["ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND"] = claude_command
    if bool(getattr(settings, "telegram_agent_claude_enabled", False)) and claude_model:
        env["TELEGRAM_AGENT_CLAUDE_MODEL"] = claude_model
        env["ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL"] = claude_model
    if codex_command:
        env["TELEGRAM_AGENT_CODEX_COMMAND"] = codex_command
        env["ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND"] = codex_command
    if codex_model:
        env["TELEGRAM_AGENT_CODEX_MODEL"] = codex_model
        env["ROUGHCUT_ACP_BRIDGE_CODEX_MODEL"] = codex_model
    env.setdefault("PYTHONIOENCODING", "utf-8")
    timeout = max(30, int(getattr(settings, "telegram_agent_task_timeout_sec", 900)))
    result = subprocess.run(
        bridge_command,
        shell=True,
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=str(repo_root),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = decode_process_output(result.stdout)
    stderr = decode_process_output(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(stderr or stdout or f"ACP bridge exited with code {result.returncode}")
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        parsed = {}
    excerpt_source = ""
    if isinstance(parsed, dict):
        excerpt_source = str(parsed.get("excerpt") or parsed.get("stdout") or "").strip()
    excerpt = _truncate_text(
        excerpt_source or stdout or stderr,
        max_chars=int(getattr(settings, "telegram_agent_result_max_chars", 3500)),
    )
    return {
        "provider": "acp",
        "preset": preset,
        "cwd": str(repo_root),
        "scope_path": scope_value,
        "job_id": job_id,
        "stdout": str(parsed.get("stdout") if isinstance(parsed, dict) else stdout or "").strip() or stdout,
        "stderr": str(parsed.get("stderr") if isinstance(parsed, dict) else stderr or "").strip() or stderr,
        "excerpt": excerpt,
        "returncode": result.returncode,
    }


def _render_prompt(
    *,
    task_id: str,
    chat_id: str,
    provider: str,
    preset: str,
    task_text: str,
    scope_path: str,
    job_id: str,
) -> str:
    preset_config = get_preset(provider, preset)
    if preset_config is None:
        raise ValueError(f"Unknown preset: {provider}/{preset}")
    scope_block = f"关注范围：{scope_path}\n" if scope_path else ""
    job_block = f"关联 Job ID：{job_id}\n" if job_id else ""
    task_block = f"附加任务：{task_text}\n" if task_text else ""
    rendered = preset_config.prompt_template.format(
        task=task_text,
        task_block=task_block,
        scope_block=scope_block,
        job_block=job_block,
    ).strip()
    context_blocks = [
        _build_project_rules_block(scope_path=scope_path),
        _build_recent_task_memory_block(chat_id=chat_id, current_task_id=task_id),
    ]
    extra_context = "\n\n".join(block for block in context_blocks if block)
    if extra_context:
        rendered = f"{rendered}\n\n{extra_context}"
    return rendered.strip()


def _build_project_rules_block(*, scope_path: str) -> str:
    lines = [
        "项目规则与默认约束：",
        "- 当前仓库是 RoughCut，核心链路包括 FastAPI API、React/Vite 控制台、Celery worker、Telegram agent 与 ACP bridge。",
        "- 新需求默认优先结构收敛和可维护性，不为旧页面/旧配置保留兼容层，除非需求明确要求兼容。",
        "- 工程改动应保持最小可行实现，优先复用现有模块，并尽量补上直接相关测试。",
        "- 日常命令优先从仓库根目录使用 pnpm；Python 依赖和 CLI 仍由 uv 管理。",
        "- 若本次提供了 scope_path，只在该范围及其直接依赖内收敛改动；确有必要再扩大范围。",
    ]
    if scope_path:
        lines.append(f"- 当前优先关注范围：{scope_path}")
    return "\n".join(lines)


def _build_recent_task_memory_block(*, chat_id: str, current_task_id: str, limit: int = 4) -> str:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return ""
    try:
        store = TelegramAgentTaskStore(_state_dir_path() / "tasks.json")
        records = [
            item
            for item in store.list_for_chat(normalized_chat_id, limit=max(1, limit + 2))
            if item.task_id != str(current_task_id or "").strip()
        ]
    except Exception:
        return ""
    if not records:
        return ""

    lines = ["同会话近期任务记忆（仅供参考，不要盲从旧结论）："]
    for item in records[:limit]:
        timestamp = _format_task_timestamp(item.updated_at)
        lines.append(f"- {timestamp} | {item.provider}/{item.preset} | {item.status}")
        if item.task_text:
            lines.append(f"  请求：{_compact_text(item.task_text, max_chars=180)}")
        summary_text = item.result_excerpt or item.error_text
        if summary_text:
            label = "结果" if item.result_excerpt else "错误"
            lines.append(f"  {label}：{_compact_text(summary_text, max_chars=220)}")
    return "\n".join(lines)


def _state_dir_path() -> Path:
    settings = get_settings()
    state_dir = Path(str(getattr(settings, "telegram_agent_state_dir", "") or "").strip() or "data/telegram-agent")
    if not state_dir.is_absolute():
        state_dir = _repo_root() / state_dir
    return state_dir


def _format_task_timestamp(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown-time"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw[:16]


def _compact_text(text: str, *, max_chars: int) -> str:
    normalized = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 16)].rstrip() + " ...[truncated]"


def _normalize_scope(scope_path: str, repo_root: Path) -> str:
    raw = str(scope_path or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (repo_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if repo_root not in {candidate, *candidate.parents}:
        raise ValueError(f"scope_path must stay under repo root: {raw}")
    try:
        return str(candidate.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return ""


def _truncate_text(text: str, *, max_chars: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 16)].rstrip() + "\n...[truncated]"


def _default_acp_bridge_command(repo_root: Path) -> str:
    script = repo_root / "scripts" / "acp_bridge.py"
    return f'"{sys.executable}" "{script}"'


def _configured_acp_backends(settings) -> list[str]:
    backends: list[str] = []
    claude_enabled = bool(getattr(settings, "telegram_agent_claude_enabled", False))
    explicit_primary = normalize_coding_backend_name(
        getattr(settings, "acp_bridge_backend", "")
        or os.getenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "")
    )
    explicit_fallback = normalize_coding_backend_name(
        getattr(settings, "acp_bridge_fallback_backend", "")
        or os.getenv("ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND", "")
    )
    for item in (
        explicit_primary,
        explicit_fallback,
        *infer_coding_backends(settings, claude_enabled=claude_enabled),
    ):
        normalized = normalize_coding_backend_name(item)
        if normalized not in {"claude", "codex"}:
            continue
        if normalized == "claude" and not claude_enabled:
            continue
        if normalized not in backends:
            backends.append(normalized)
    return backends
