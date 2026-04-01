from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from roughcut.telegram.output_codec import decode_process_output


def run_codex_exec(payload: dict[str, Any]) -> dict[str, Any]:
    repo_root = Path(str(payload.get("repo_root") or ".")).resolve()
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")

    command_name = str(
        payload.get("command")
        or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_COMMAND", "")
        or "codex"
    ).strip()
    resolved = shutil.which(command_name)
    if not resolved:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")

    model_name = str(payload.get("model") or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_MODEL", "")).strip()
    sandbox_mode = str(
        payload.get("sandbox")
        or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_SANDBOX", "danger-full-access")
        or "danger-full-access"
    ).strip()
    timeout_sec = max(
        30,
        int(
            payload.get("timeout_sec")
            or os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_TIMEOUT_SEC", "900")
            or "900"
        ),
    )

    with tempfile.TemporaryDirectory(prefix="roughcut-host-codex-") as temp_dir:
        stdout_override_path = Path(temp_dir) / "last-message.txt"
        command = [
            resolved,
            "-a",
            "never",
        ]
        if model_name:
            command.extend(["-m", model_name])
        command.extend(
            [
                "exec",
                "--color",
                "never",
                "-C",
                str(repo_root),
                "-s",
                sandbox_mode,
                "-o",
                str(stdout_override_path),
                prompt,
            ]
        )
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_sec,
            cwd=str(repo_root),
            env={**os.environ.copy(), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = decode_process_output(stdout_override_path.read_bytes()) if stdout_override_path.exists() else ""
        if not stdout:
            stdout = decode_process_output(result.stdout)
        stderr = decode_process_output(result.stderr)
        excerpt = stdout or stderr
        if len(excerpt) > 3500:
            excerpt = excerpt[:3484].rstrip() + "\n...[truncated]"
        if result.returncode != 0:
            raise RuntimeError(stderr or stdout or f"codex exited with code {result.returncode}")
        return {
            "provider": "acp",
            "backend": "codex",
            "stdout": stdout,
            "stderr": stderr,
            "excerpt": excerpt,
            "returncode": result.returncode,
            "host_bridge": True,
        }

