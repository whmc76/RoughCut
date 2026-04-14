from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import infer_coding_backends, get_settings, normalize_coding_backend_name, resolve_coding_backend_model
from roughcut.telegram.output_codec import decode_process_output


def _configured_backend() -> str:
    explicit = normalize_coding_backend_name(os.getenv("ROUGHCUT_ACP_BRIDGE_BACKEND", ""))
    if explicit:
        return explicit
    try:
        backends = infer_coding_backends(get_settings())
    except Exception:
        backends = ["codex"]
    return backends[0] if backends else "codex"


def _configured_fallback_backend() -> str:
    explicit = normalize_coding_backend_name(os.getenv("ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND", ""))
    if explicit:
        return explicit
    try:
        backends = infer_coding_backends(get_settings())
    except Exception:
        backends = ["codex"]
    return backends[1] if len(backends) > 1 else ""


def build_backend_command(payload: dict[str, Any], *, backend: str | None = None) -> tuple[list[str], Path, int]:
    backend = normalize_coding_backend_name(backend or _configured_backend() or "codex") or "codex"
    repo_root = Path(str(payload.get("repo_root") or ".")).resolve()
    prompt = str(payload.get("prompt") or payload.get("task") or "").strip()
    if not prompt:
        raise ValueError("payload.prompt is required")
    try:
        settings = get_settings()
    except Exception:
        settings = None

    timeout = int(
        os.getenv(
            "ROUGHCUT_ACP_BRIDGE_TIMEOUT_SEC",
            os.getenv("TELEGRAM_AGENT_TASK_TIMEOUT_SEC", "900"),
        )
        or "900"
    )
    if backend == "claude":
        command_name = (
            str(os.getenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND", "")).strip()
            or str(os.getenv("TELEGRAM_AGENT_CLAUDE_COMMAND", "")).strip()
            or "claude"
        )
        resolved = shutil.which(command_name)
        if not resolved:
            raise RuntimeError(f"Claude command not found in PATH: {command_name}")

        permission_mode = str(os.getenv("ROUGHCUT_ACP_BRIDGE_PERMISSION_MODE", "acceptEdits") or "acceptEdits").strip()
        model_name = resolve_coding_backend_model(
            "claude",
            settings=settings,
            explicit_model=(
                str(os.getenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL", "")).strip()
                or str(os.getenv("TELEGRAM_AGENT_CLAUDE_MODEL", "")).strip()
            ),
        )
        command = [
            resolved,
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
        return command, repo_root, max(30, timeout)

    if backend == "codex":
        command_name = (
            str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND", "")).strip()
            or str(os.getenv("TELEGRAM_AGENT_CODEX_COMMAND", "")).strip()
            or "codex"
        )
        resolved = shutil.which(command_name)
        if not resolved:
            raise RuntimeError(f"Codex command not found in PATH: {command_name}")

        sandbox_mode = str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_SANDBOX", "danger-full-access") or "danger-full-access").strip()
        model_name = resolve_coding_backend_model(
            "codex",
            settings=settings,
            explicit_model=(
                str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_MODEL", "")).strip()
                or str(os.getenv("TELEGRAM_AGENT_CODEX_MODEL", "")).strip()
            ),
        )
        command = [
            resolved,
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
            prompt,
        ])
        return command, repo_root, max(30, timeout)

    raise ValueError(f"Unsupported ACP bridge backend: {backend}")


def _run_backend(payload: dict[str, Any], *, backend: str) -> dict[str, Any]:
    if backend == "codex":
        proxy_url = str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "") or "").strip()
        if proxy_url:
            headers = {"Content-Type": "application/json"}
            proxy_token = str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN", "") or "").strip()
            if proxy_token:
                headers["Authorization"] = f"Bearer {proxy_token}"
            timeout = int(
                os.getenv(
                    "ROUGHCUT_ACP_BRIDGE_TIMEOUT_SEC",
                    os.getenv("TELEGRAM_AGENT_TASK_TIMEOUT_SEC", "900"),
                )
                or "900"
            )
            response = httpx.post(
                proxy_url,
                json={
                    "repo_root": str(Path(str(payload.get("repo_root") or ".")).resolve()),
                    "prompt": str(payload.get("prompt") or payload.get("task") or "").strip(),
                    "model": resolve_coding_backend_model(
                        "codex",
                        settings=get_settings(),
                        explicit_model=(
                            str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_MODEL", "")).strip()
                            or str(os.getenv("TELEGRAM_AGENT_CODEX_MODEL", "")).strip()
                        ),
                    ),
                    "sandbox": str(os.getenv("ROUGHCUT_ACP_BRIDGE_CODEX_SANDBOX", "danger-full-access") or "danger-full-access").strip(),
                    "timeout_sec": max(30, timeout),
                },
                headers=headers,
                timeout=max(30, timeout),
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Codex host bridge returned a non-object response")
            return result

    command, cwd, timeout = build_backend_command(payload, backend=backend)
    stdout_override_path: Path | None = None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if backend == "codex":
        temp_dir = tempfile.TemporaryDirectory(prefix="roughcut-acp-codex-")
        stdout_override_path = Path(temp_dir.name) / "last-message.txt"
        command = [*command[:-1], "-o", str(stdout_override_path), command[-1]]
    try:
        stdin_payload = payload.get("prompt") if backend == "claude" else None
        result = subprocess.run(
            command,
            input=str(stdin_payload or "").encode("utf-8") if backend == "claude" else None,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd),
            env={**os.environ.copy(), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8")},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout = ""
        if stdout_override_path and stdout_override_path.exists():
            stdout = decode_process_output(stdout_override_path.read_bytes())
        if not stdout:
            stdout = decode_process_output(result.stdout)
        stderr = decode_process_output(result.stderr)
        excerpt = stdout or stderr
        if len(excerpt) > 3500:
            excerpt = excerpt[:3484].rstrip() + "\n...[truncated]"
        if result.returncode != 0:
            raise RuntimeError(stderr or stdout or f"bridge backend exited with code {result.returncode}")
        return {
            "provider": "acp",
            "backend": backend,
            "stdout": stdout,
            "stderr": stderr,
            "excerpt": excerpt,
            "returncode": result.returncode,
        }
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def run_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    primary_backend = _configured_backend()
    fallback_backend = _configured_fallback_backend()
    backends: list[str] = []
    for item in (primary_backend, fallback_backend):
        normalized = str(item or "").strip().lower()
        if normalized and normalized not in backends:
            backends.append(normalized)
    if not backends:
        backends = ["codex"]

    last_error: Exception | None = None
    for index, backend in enumerate(backends):
        try:
            result = _run_backend(payload, backend=backend)
            if index > 0:
                result["fallback_from"] = primary_backend
            return result
        except Exception as exc:
            last_error = exc
            if index == len(backends) - 1:
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("No ACP bridge backend available")


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
