from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def build_backend_command(payload: dict[str, Any]) -> tuple[list[str], Path, int]:
    backend = str(os.getenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude") or "claude").strip().lower()
    repo_root = Path(str(payload.get("repo_root") or ".")).resolve()
    prompt = str(payload.get("prompt") or payload.get("task") or "").strip()
    if not prompt:
        raise ValueError("payload.prompt is required")

    timeout = int(
        os.getenv(
            "ROUGHCUT_ACP_BRIDGE_TIMEOUT_SEC",
            os.getenv("TELEGRAM_AGENT_TASK_TIMEOUT_SEC", "900"),
        )
        or "900"
    )
    if backend != "claude":
        raise ValueError(f"Unsupported ACP bridge backend: {backend}")

    command_name = (
        str(os.getenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND", "")).strip()
        or str(os.getenv("TELEGRAM_AGENT_CLAUDE_COMMAND", "")).strip()
        or "claude"
    )
    resolved = shutil.which(command_name)
    if not resolved:
        raise RuntimeError(f"Claude command not found in PATH: {command_name}")

    permission_mode = str(os.getenv("ROUGHCUT_ACP_BRIDGE_PERMISSION_MODE", "acceptEdits") or "acceptEdits").strip()
    command = [
        resolved,
        "-p",
        "--permission-mode",
        permission_mode,
        "--output-format",
        "text",
        "--add-dir",
        str(repo_root),
        prompt,
    ]
    return command, repo_root, max(30, timeout)


def run_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    command, cwd, timeout = build_backend_command(payload)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(cwd),
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    excerpt = stdout or stderr
    if len(excerpt) > 3500:
        excerpt = excerpt[:3484].rstrip() + "\n...[truncated]"
    if result.returncode != 0:
        raise RuntimeError(stderr or stdout or f"bridge backend exited with code {result.returncode}")
    return {
        "provider": "acp",
        "backend": str(os.getenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude") or "claude").strip().lower(),
        "stdout": stdout,
        "stderr": stderr,
        "excerpt": excerpt,
        "returncode": result.returncode,
    }


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.stderr.write(json.dumps({"error": "stdin payload is required"}, ensure_ascii=False))
        return 1
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        result = run_bridge(payload)
    except Exception as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
