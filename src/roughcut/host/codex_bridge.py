from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from roughcut.telegram.output_codec import decode_process_output


def _resolve_codex_command(command_name: str) -> str | None:
    normalized_command = str(command_name or "").strip().lower()
    explicit = None
    if normalized_command == "codex":
        explicit = shutil.which("codex.exe")
    if not explicit:
        explicit = shutil.which(command_name)
    if not explicit:
        return None
    explicit_path = Path(explicit)
    normalized_name = explicit_path.name.lower()
    if normalized_name == "codex.exe":
        return str(explicit_path)

    candidates: list[Path] = []

    windows_apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    if windows_apps.exists():
        for sibling_name in ("codex.exe", "codex"):
            candidate = windows_apps / sibling_name
            if candidate.exists():
                candidates.append(candidate)

    package_root = Path(r"C:\Program Files\WindowsApps")
    if package_root.exists():
        for child in sorted(package_root.glob("OpenAI.Codex_*"), reverse=True):
            candidate = child / "app" / "resources" / "codex.exe"
            if candidate.exists():
                candidates.append(candidate)

    for sibling_name in ("codex.exe", "codex"):
        sibling = explicit_path.with_name(sibling_name)
        if sibling.exists():
            candidates.append(sibling)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(explicit_path)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


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
    resolved = _resolve_codex_command(command_name)
    if not resolved:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")
    fallback_resolved = shutil.which(command_name)
    command_candidates: list[str] = [resolved]
    if fallback_resolved and fallback_resolved not in command_candidates:
        command_candidates.append(fallback_resolved)

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
        output_schema = payload.get("output_schema")
        output_schema_path: Path | None = None
        if isinstance(output_schema, dict):
            output_schema_path = Path(temp_dir) / "output-schema.json"
            output_schema_path.write_text(json.dumps(output_schema, ensure_ascii=False), encoding="utf-8")
        elif output_schema:
            output_schema_path = Path(str(output_schema)).resolve()
        last_permission_error: PermissionError | None = None
        for candidate_command in command_candidates:
            command = [
                candidate_command,
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
                ]
            )
            if output_schema_path is not None:
                command.extend(["--output-schema", str(output_schema_path)])
            command.append("-")
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(repo_root),
                    env={**os.environ.copy(), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")},
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except PermissionError as exc:
                last_permission_error = exc
                continue
            try:
                stdout_bytes, stderr_bytes = process.communicate(
                    input=prompt.encode("utf-8"),
                    timeout=timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                _terminate_process_tree(process)
                try:
                    stdout_bytes, stderr_bytes = process.communicate(timeout=5)
                except Exception:
                    stdout_bytes = exc.output or b""
                    stderr_bytes = exc.stderr or b""
                stdout = (
                    decode_process_output(stdout_override_path.read_bytes())
                    if stdout_override_path.exists()
                    else decode_process_output(stdout_bytes)
                )
                stderr = decode_process_output(stderr_bytes)
                raise TimeoutError(
                    f"codex exec timed out after {timeout_sec}s"
                    + (f": {stderr.strip()}" if str(stderr or "").strip() else "")
                )
            stdout = decode_process_output(stdout_override_path.read_bytes()) if stdout_override_path.exists() else ""
            if not stdout:
                stdout = decode_process_output(stdout_bytes)
            stderr = decode_process_output(stderr_bytes)
            excerpt = stdout or stderr
            if len(excerpt) > 3500:
                excerpt = excerpt[:3484].rstrip() + "\n...[truncated]"
            if process.returncode != 0:
                raise RuntimeError(stderr or stdout or f"codex exited with code {process.returncode}")
            return {
                "provider": "acp",
                "backend": "codex",
                "stdout": stdout,
                "stderr": stderr,
                "excerpt": excerpt,
                "returncode": process.returncode,
                "host_bridge": True,
            }
        if last_permission_error is not None:
            raise last_permission_error
