from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.telegram.presets import get_preset


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def execute_agent_preset(
    *,
    provider: str,
    preset: str,
    task_text: str,
    scope_path: str = "",
    job_id: str = "",
) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "claude":
        return _execute_claude_preset(
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    if normalized_provider == "codex":
        return _execute_codex_preset(
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    if normalized_provider == "acp":
        return _execute_acp_preset(
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def _execute_claude_preset(*, preset: str, task_text: str, scope_path: str, job_id: str) -> dict[str, Any]:
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
    model_name = str(
        getattr(settings, "telegram_agent_claude_model", "")
        or os.getenv("TELEGRAM_AGENT_CLAUDE_MODEL", "")
    ).strip()

    repo_root = _repo_root()
    scope_value = _normalize_scope(scope_path, repo_root)
    prompt = _render_prompt(
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
    command.append(prompt)
    timeout = max(30, int(getattr(settings, "telegram_agent_task_timeout_sec", 900)))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(repo_root),
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
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


def _execute_codex_preset(*, preset: str, task_text: str, scope_path: str, job_id: str) -> dict[str, Any]:
    preset_config = get_preset("codex", preset)
    if preset_config is None:
        raise ValueError(f"Unknown Codex preset: {preset}")

    command_name = str(
        getattr(get_settings(), "telegram_agent_codex_command", "")
        or os.getenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
        or "codex"
    ).strip()
    resolved_command = shutil.which(command_name)
    if not resolved_command:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")

    settings = get_settings()
    repo_root = _repo_root()
    scope_value = _normalize_scope(scope_path, repo_root)
    prompt = _render_prompt(
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
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(repo_root),
            env=os.environ.copy(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = ""
        if output_file.exists():
            stdout = output_file.read_text(encoding="utf-8", errors="replace").strip()
        if not stdout:
            stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
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


def _execute_acp_preset(*, preset: str, task_text: str, scope_path: str, job_id: str) -> dict[str, Any]:
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
        "provider": "acp",
        "preset": preset,
        "task": task_text,
        "scope_path": scope_value,
        "job_id": job_id,
        "repo_root": str(repo_root),
        "prompt": _render_prompt(
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
    timeout = max(30, int(getattr(settings, "telegram_agent_task_timeout_sec", 900)))
    result = subprocess.run(
        bridge_command,
        shell=True,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(repo_root),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
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


def _render_prompt(*, provider: str, preset: str, task_text: str, scope_path: str, job_id: str) -> str:
    preset_config = get_preset(provider, preset)
    if preset_config is None:
        raise ValueError(f"Unknown preset: {provider}/{preset}")
    scope_block = f"关注范围：{scope_path}\n" if scope_path else ""
    job_block = f"关联 Job ID：{job_id}\n" if job_id else ""
    task_block = f"附加任务：{task_text}\n" if task_text else ""
    return preset_config.prompt_template.format(
        task=task_text,
        task_block=task_block,
        scope_block=scope_block,
        job_block=job_block,
    ).strip()


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
